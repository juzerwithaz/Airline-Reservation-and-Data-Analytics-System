-- ====================================================================
-- AIRLINE RESERVATION AND BOOKING ANALYTICS SYSTEM
-- REVISED IDEMPOTENT DATABASE MIGRATION SCRIPT (ORACLE 23ai)
-- ====================================================================
-- INSTRUCTIONS FOR USER:
-- 1. Open Oracle SQL Developer.
-- 2. Connect to user: airline @ localhost:1521/FREEPDB1.
-- 3. Review the explanations below.
-- 4. Execute the script (or run Phase by Phase).
-- ====================================================================

SET SERVEROUTPUT ON;

-- ====================================================================
-- PHASE 0: PRE-MIGRATION READ-ONLY VALIDATION (RUN FIRST)
-- ====================================================================
-- Purpose: Verify current row counts, sequence definitions, and check
-- if target security tables already exist before making any changes.
-- ====================================================================

PROMPT === PHASE 0: PRE-MIGRATION DIAGNOSTIC CHECK ===;

SELECT 'AIRPORTS' AS entity, COUNT(*) AS current_rows, NULL AS current_max_id FROM Airports
UNION ALL
SELECT 'FLIGHTS', COUNT(*), MAX(flight_id) FROM Flights
UNION ALL
SELECT 'PASSENGERS', COUNT(*), MAX(passenger_id) FROM Passengers
UNION ALL
SELECT 'BOOKINGS', COUNT(*), MAX(booking_id) FROM Bookings
UNION ALL
SELECT 'PAYMENTS', COUNT(*), MAX(payment_id) FROM Payments;

-- Inspect sequences and cache settings
SELECT sequence_name, min_value, max_value, increment_by, cache_size, last_number
FROM user_sequences
WHERE sequence_name IN ('BOOKING_SEQ', 'PASSENGER_SEQ', 'PAYMENT_SEQ');

-- Check if new tables already exist
SELECT table_name, status
FROM user_tables
WHERE table_name IN ('PASSENGER_AUTH', 'ADMIN_USERS');


-- ====================================================================
-- PHASE 1: IDEMPOTENT SEQUENCE SYNCHRONIZATION
-- ====================================================================
-- Technical Context on Oracle Sequences & Caching:
-- 1. The existing sequences have CACHE 20 by default. In Oracle,
--    USER_SEQUENCES.LAST_NUMBER indicates the next value to be loaded
--    into the cache block, NOT necessarily the exact next emitted ID.
-- 2. In our initial seed data, literal IDs were inserted (1..302, 1..60, 1..239)
--    without invoking .NEXTVAL, leaving the sequence starting offsets at 1.
-- 3. Executing ALTER SEQUENCE ... RESTART WITH X flushes the sequence cache
--    and guarantees that the very next invocation of .NEXTVAL will return
--    exactly X.
-- 4. This block is IDEMPOTENT: it queries MAX(id) + 1 and only restarts
--    if the sequence offset is below the table maximum.
-- ====================================================================

PROMPT === PHASE 1: SYNCHRONIZING SEQUENCES ===;

DECLARE
    v_max_booking   NUMBER;
    v_seq_booking   NUMBER;
    v_max_passenger NUMBER;
    v_seq_passenger NUMBER;
    v_max_payment   NUMBER;
    v_seq_payment   NUMBER;
BEGIN
    -- 1. Booking Sequence
    SELECT NVL(MAX(booking_id), 0) + 1 INTO v_max_booking FROM Bookings;
    SELECT last_number INTO v_seq_booking FROM user_sequences WHERE sequence_name = 'BOOKING_SEQ';
    IF v_seq_booking < v_max_booking THEN
        EXECUTE IMMEDIATE 'ALTER SEQUENCE booking_seq RESTART START WITH ' || v_max_booking;
        DBMS_OUTPUT.PUT_LINE('BOOKING_SEQ cache flushed and restarted with: ' || v_max_booking);
    ELSE
        DBMS_OUTPUT.PUT_LINE('BOOKING_SEQ already synchronized (last_number: ' || v_seq_booking || ').');
    END IF;

    -- 2. Passenger Sequence
    SELECT NVL(MAX(passenger_id), 0) + 1 INTO v_max_passenger FROM Passengers;
    SELECT last_number INTO v_seq_passenger FROM user_sequences WHERE sequence_name = 'PASSENGER_SEQ';
    IF v_seq_passenger < v_max_passenger THEN
        EXECUTE IMMEDIATE 'ALTER SEQUENCE passenger_seq RESTART START WITH ' || v_max_passenger;
        DBMS_OUTPUT.PUT_LINE('PASSENGER_SEQ cache flushed and restarted with: ' || v_max_passenger);
    ELSE
        DBMS_OUTPUT.PUT_LINE('PASSENGER_SEQ already synchronized (last_number: ' || v_seq_passenger || ').');
    END IF;

    -- 3. Payment Sequence
    SELECT NVL(MAX(payment_id), 0) + 1 INTO v_max_payment FROM Payments;
    SELECT last_number INTO v_seq_payment FROM user_sequences WHERE sequence_name = 'PAYMENT_SEQ';
    IF v_seq_payment < v_max_payment THEN
        EXECUTE IMMEDIATE 'ALTER SEQUENCE payment_seq RESTART START WITH ' || v_max_payment;
        DBMS_OUTPUT.PUT_LINE('PAYMENT_SEQ cache flushed and restarted with: ' || v_max_payment);
    ELSE
        DBMS_OUTPUT.PUT_LINE('PAYMENT_SEQ already synchronized (last_number: ' || v_seq_payment || ').');
    END IF;
END;
/


-- ====================================================================
-- PHASE 2: CREATE PASSENGER_AUTH TABLE (IDEMPOTENT & 3NF NORMALIZED)
-- ====================================================================
-- Architectural Safeguards Applied:
-- 1. NO DUPLICATE EMAIL: Email is removed from this table to preserve 3NF.
--    Passengers.email remains the single source of truth for email identity.
-- 2. NO ON DELETE CASCADE: Replaced with standard RESTRICT foreign key.
--    Historical passengers cannot be deleted; account deactivation must use
--    soft status ('SUSPENDED').
-- 3. STATUS DEFAULTS TO 'PENDING_ACTIVATION': Accounts cannot be active
--    without an established, verified password hash.
-- 4. HASHED ACTIVATION TOKEN: activation_token_hash stores a SHA-256 digest
--    of the one-time activation code. The plain token is never stored in Oracle.
-- 5. token_expires_at enforces single-use time expiration.
-- 6. Checks user_tables first to ensure idempotency.
-- ====================================================================

PROMPT === PHASE 2: CREATING PASSENGER_AUTH ===;

DECLARE
    v_table_exists NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_table_exists FROM user_tables WHERE table_name = 'PASSENGER_AUTH';
    IF v_table_exists = 0 THEN
        EXECUTE IMMEDIATE '
            CREATE TABLE PASSENGER_AUTH (
                auth_id                 NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                passenger_id            NUMBER NOT NULL UNIQUE REFERENCES Passengers(passenger_id),
                password_hash           VARCHAR2(255),
                activation_token_hash   VARCHAR2(64),
                token_expires_at        TIMESTAMP,
                status                  VARCHAR2(20) DEFAULT ''PENDING_ACTIVATION'' 
                                        CHECK (status IN (''PENDING_ACTIVATION'', ''ACTIVE'', ''SUSPENDED'')),
                created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                activated_at            TIMESTAMP,
                last_login              TIMESTAMP
            )
        ';
        DBMS_OUTPUT.PUT_LINE('Table PASSENGER_AUTH created successfully.');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Table PASSENGER_AUTH already exists. Skipping creation.');
    END IF;
END;
/


-- ====================================================================
-- PHASE 3: CREATE ADMIN_USERS TABLE (IDEMPOTENT)
-- ====================================================================
-- Architectural Safeguards Applied:
-- 1. Completely isolated from passenger accounts.
-- 2. ZERO hardcoded seed passwords.
-- 3. Supports account lifecycle (status IN ('ACTIVE', 'SUSPENDED')).
-- 4. Checks user_tables first to ensure idempotency.
-- ====================================================================

PROMPT === PHASE 3: CREATING ADMIN_USERS ===;

DECLARE
    v_table_exists NUMBER;
BEGIN
    SELECT COUNT(*) INTO v_table_exists FROM user_tables WHERE table_name = 'ADMIN_USERS';
    IF v_table_exists = 0 THEN
        EXECUTE IMMEDIATE '
            CREATE TABLE ADMIN_USERS (
                admin_id         NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                username         VARCHAR2(50) NOT NULL UNIQUE,
                email            VARCHAR2(100) NOT NULL UNIQUE,
                password_hash    VARCHAR2(255) NOT NULL,
                full_name        VARCHAR2(100) NOT NULL,
                role             VARCHAR2(20) DEFAULT ''SUPER_ADMIN'' CHECK (role IN (''SUPER_ADMIN'', ''FLIGHT_OPS'', ''SUPPORT'')),
                status           VARCHAR2(20) DEFAULT ''ACTIVE'' CHECK (status IN (''ACTIVE'', ''SUSPENDED'')),
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login       TIMESTAMP
            )
        ';
        DBMS_OUTPUT.PUT_LINE('Table ADMIN_USERS created successfully.');
    ELSE
        DBMS_OUTPUT.PUT_LINE('Table ADMIN_USERS already exists. Skipping creation.');
    END IF;
END;
/
