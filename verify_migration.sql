-- ====================================================================
-- AIRLINE RESERVATION AND BOOKING ANALYTICS SYSTEM
-- POST-MIGRATION VERIFICATION SCRIPT (ORACLE 23ai)
-- ====================================================================
-- INSTRUCTIONS FOR USER:
-- Execute this script in Oracle SQL Developer AFTER running schema_migrations.sql.
-- ====================================================================

SET SERVEROUTPUT ON;

PROMPT =======================================================;
PROMPT POST-MIGRATION SYSTEM HEALTH & INTEGRITY CHECK
PROMPT =======================================================;

-- 1. VERIFY ORIGINAL DATA COUNTS REMAIN EXACTLY INTACT
PROMPT 1. Verifying Original Table Row Counts...;

SELECT 
    table_name,
    actual_rows,
    expected_rows,
    CASE WHEN actual_rows = expected_rows THEN 'PASS [Row Count Intact]' ELSE 'FAIL [Row Count Altered]' END AS validation_result
FROM (
    SELECT 'AIRPORTS' AS table_name, COUNT(*) AS actual_rows, 10 AS expected_rows FROM Airports
    UNION ALL
    SELECT 'FLIGHTS', COUNT(*), 20 FROM Flights
    UNION ALL
    SELECT 'PASSENGERS', COUNT(*), 60 FROM Passengers
    UNION ALL
    SELECT 'BOOKINGS', COUNT(*), 302 FROM Bookings
    UNION ALL
    SELECT 'PAYMENTS', COUNT(*), 239 FROM Payments
);

-- 2. VERIFY NEW SECURITY TABLES EXIST
PROMPT 2. Verifying New Security Tables...;

SELECT 
    t.target_table,
    CASE WHEN ut.table_name IS NOT NULL THEN 'PASS [Table Created]' ELSE 'FAIL [Table Missing]' END AS creation_status
FROM (
    SELECT 'PASSENGER_AUTH' AS target_table FROM dual
    UNION ALL
    SELECT 'ADMIN_USERS' FROM dual
) t
LEFT JOIN user_tables ut ON t.target_table = ut.table_name;

-- 3. VERIFY PASSENGER_AUTH SCHEMA & CONSTRAINTS
PROMPT 3. Verifying PASSENGER_AUTH Structure & Normalized Foreign Key...;

-- Confirm no redundant email column exists (3NF compliance)
SELECT 
    column_name, 
    data_type, 
    data_default,
    nullable
FROM user_tab_cols
WHERE table_name = 'PASSENGER_AUTH'
ORDER BY column_id;

-- Confirm foreign key has NO cascading delete (delete_rule = 'NO ACTION')
SELECT 
    constraint_name,
    table_name,
    r_constraint_name,
    delete_rule,
    status
FROM user_constraints
WHERE table_name = 'PASSENGER_AUTH' AND constraint_type = 'R';

-- 4. VERIFY SEQUENCE SYNCHRONIZATION ALIGNMENT
PROMPT 4. Verifying Sequence Offsets vs Table Maxima...;
-- Technical Context:
-- With CACHE 20, ALTER SEQUENCE ... RESTART WITH X resets the sequence so that
-- the next NEXTVAL will deliver X. USER_SEQUENCES.LAST_NUMBER reflects the upper
-- boundary of the cached range.

SELECT
    s.sequence_name,
    s.cache_size,
    s.last_number AS sequence_cache_boundary,
    m.max_table_id,
    CASE 
        WHEN s.last_number >= m.max_table_id THEN 'PASS [Sequence Cache Offset >= Table Maximum]' 
        ELSE 'FAIL [Sequence Offset Below Max ID]' 
    END AS sequence_synchronization_status
FROM user_sequences s
JOIN (
    SELECT 'BOOKING_SEQ' AS seq_name, MAX(booking_id) AS max_table_id FROM Bookings
    UNION ALL
    SELECT 'PASSENGER_SEQ', MAX(passenger_id) FROM Passengers
    UNION ALL
    SELECT 'PAYMENT_SEQ', MAX(payment_id) FROM Payments
) m ON s.sequence_name = m.seq_name;

PROMPT =======================================================;
PROMPT INTEGRITY CHECK COMPLETE
PROMPT =======================================================;
