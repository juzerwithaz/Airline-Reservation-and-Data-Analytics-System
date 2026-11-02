import os
import json
import hashlib
import secrets
from typing import Any, Dict, List, Optional, Tuple
import oracledb
import pandas as pd
from dotenv import load_dotenv

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
    _ph: Optional[PasswordHasher] = PasswordHasher()
except ImportError:
    _ph = None

# Load environment variables from .env
load_dotenv()


def get_db_credentials() -> Tuple[str, str, str]:
    """
    Retrieve Oracle DB credentials, checking Streamlit Secrets first
    (for Streamlit Community Cloud deployment), then falling back to .env / os.getenv.
    """
    user = os.getenv("ORACLE_USER", "airline")
    password = os.getenv("ORACLE_PASSWORD", "airline123")
    dsn = os.getenv("ORACLE_DSN", "localhost:1521/FREEPDB1")

    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            user = st.secrets.get("ORACLE_USER", user)
            password = st.secrets.get("ORACLE_PASSWORD", password)
            dsn = st.secrets.get("ORACLE_DSN", dsn)
    except Exception:
        pass

    return user, password, dsn


def get_connection() -> oracledb.Connection:
    """
    Establish a connection to Oracle Database in Thin Mode.
    No Oracle Instant Client or binary installation is required.
    """
    user, password, dsn = get_db_credentials()
    try:
        return oracledb.connect(
            user=user,
            password=password,
            dsn=dsn,
        )
    except oracledb.DatabaseError as e:
        error_obj, = e.args
        raise RuntimeError(
            f"Oracle Database connection failed: {error_obj.message} (Code: {error_obj.code})"
        ) from e


def test_connection() -> Dict[str, Any]:
    """
    Test connectivity and return server version and current user.
    """
    user, _, _ = get_db_credentials()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT USER, BANNER FROM v$version WHERE ROWNUM = 1")
            row = cursor.fetchone()
            return {
                "status": "connected",
                "user": row[0] if row else user,
                "banner": row[1] if row else f"Oracle DB (version {conn.version})",
                "version": conn.version,
            }
    finally:
        conn.close()


def fetch_df(sql: str, params: Optional[Any] = None) -> pd.DataFrame:
    """
    Execute a SELECT query with optional bind parameters and return a pandas DataFrame.
    Column names are returned in lower_case for clean, consistent pythonic access.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if params is not None:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            if cursor.description is None:
                return pd.DataFrame()

            col_names = [col[0].lower() for col in cursor.description]
            rows = cursor.fetchall()
            return pd.DataFrame(rows, columns=col_names)
    except oracledb.DatabaseError as e:
        error_obj, = e.args
        raise RuntimeError(f"Database Query Error: {error_obj.message}") from e
    finally:
        conn.close()


def fetch_one(sql: str, params: Optional[Any] = None) -> Optional[Tuple]:
    """
    Fetch a single row for a query.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if params is not None:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            return cursor.fetchone()
    finally:
        conn.close()


def refresh_route_revenue_mv() -> bool:
    """
    Refresh the materialized view ROUTE_REVENUE_MV via DBMS_MVIEW.REFRESH.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("BEGIN DBMS_MVIEW.REFRESH('ROUTE_REVENUE_MV'); END;")
        return True
    except oracledb.DatabaseError as e:
        error_obj, = e.args
        raise RuntimeError(f"Failed to refresh ROUTE_REVENUE_MV: {error_obj.message}") from e
    finally:
        conn.close()


# ====================================================================
# PASSWORD SECURITY (ARGON2ID)
# ====================================================================

def hash_password(password: str) -> str:
    """
    Hash a plain-text password using Argon2id.
    """
    if _ph is None:
        raise RuntimeError("argon2-cffi package is not installed. Run: pip install argon2-cffi")
    return _ph.hash(password)


def verify_password(password_hash: str, candidate_password: str) -> bool:
    """
    Verify a candidate password against an Argon2id hash.
    Returns True if valid, False otherwise.
    """
    if _ph is None or not password_hash:
        return False
    try:
        return _ph.verify(password_hash, candidate_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ====================================================================
# SEQUENCE GENERATION HELPERS (SAFELY SYNCHRONIZED)
# ====================================================================

def get_next_sequence_val(cursor: oracledb.Cursor, sequence_name: str) -> int:
    """
    Retrieve the next value from an Oracle sequence safely.
    Validates sequence name to prevent SQL injection.
    """
    allowed_sequences = {
        "BOOKING_SEQ": "BOOKING_SEQ",
        "PASSENGER_SEQ": "PASSENGER_SEQ",
        "PAYMENT_SEQ": "PAYMENT_SEQ",
    }
    seq = allowed_sequences.get(sequence_name.upper())
    if not seq:
        raise ValueError(f"Unknown sequence: {sequence_name}")

    cursor.execute(f"SELECT {seq}.NEXTVAL FROM DUAL")
    row = cursor.fetchone()
    if not row or row[0] is None:
        raise RuntimeError(f"Failed to fetch next value from {seq}")
    return int(row[0])


# ====================================================================
# PASSENGER AUTHENTICATION & REGISTRATION
# ====================================================================

def get_passenger_by_email(email: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a passenger and their authentication details by email.
    Email is normalized to lower case.
    """
    sql = """
        SELECT 
            p.passenger_id,
            p.name,
            p.email,
            p.phone,
            p.preferences,
            a.auth_id,
            a.password_hash,
            a.status AS auth_status,
            a.activation_token_hash,
            TO_CHAR(a.token_expires_at, 'YYYY-MM-DD HH24:MI:SS') AS token_expires_at,
            TO_CHAR(a.created_at, 'YYYY-MM-DD HH24:MI:SS') AS auth_created_at,
            TO_CHAR(a.activated_at, 'YYYY-MM-DD HH24:MI:SS') AS activated_at,
            TO_CHAR(a.last_login, 'YYYY-MM-DD HH24:MI:SS') AS last_login
        FROM Passengers p
        LEFT JOIN PASSENGER_AUTH a ON p.passenger_id = a.passenger_id
        WHERE LOWER(p.email) = LOWER(:email)
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, {"email": email.strip()})
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "passenger_id": int(row[0]),
                "name": row[1],
                "email": row[2],
                "phone": row[3],
                "preferences": row[4],
                "auth_id": int(row[5]) if row[5] is not None else None,
                "password_hash": row[6],
                "auth_status": row[7] or "NO_ACCOUNT",
                "activation_token_hash": row[8],
                "token_expires_at": row[9],
                "auth_created_at": row[10],
                "activated_at": row[11],
                "last_login": row[12],
            }
    finally:
        conn.close()


def get_passenger_by_id(passenger_id: int) -> Optional[Dict[str, Any]]:
    """
    Retrieve a passenger profile by passenger_id.
    """
    sql = """
        SELECT 
            p.passenger_id,
            p.name,
            p.email,
            p.phone,
            p.preferences,
            a.status AS auth_status,
            TO_CHAR(a.last_login, 'YYYY-MM-DD HH24:MI:SS') AS last_login
        FROM Passengers p
        LEFT JOIN PASSENGER_AUTH a ON p.passenger_id = a.passenger_id
        WHERE p.passenger_id = :pid
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, {"pid": passenger_id})
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "passenger_id": int(row[0]),
                "name": row[1],
                "email": row[2],
                "phone": row[3],
                "preferences": row[4],
                "auth_status": row[5] or "NO_ACCOUNT",
                "last_login": row[6],
            }
    finally:
        conn.close()


def register_passenger(
    name: str,
    email: str,
    phone: str,
    password: str,
    preferences: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Register a new passenger:
    1. Checks if email already exists in Passengers table.
    2. Hashes password using Argon2id.
    3. Fetches next ID from PASSENGER_SEQ.
    4. Inserts record into Passengers.
    5. Inserts auth record into PASSENGER_AUTH with status 'ACTIVE'.
    6. Commits atomically.
    """
    cleaned_email = email.strip().lower()
    if not cleaned_email or "@" not in cleaned_email:
        raise ValueError("A valid email address is required.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")

    prefs_str = json.dumps(preferences) if preferences else json.dumps({"meal": "Standard", "seat": "Aisle"})
    pwd_hash = hash_password(password)

    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cursor:
            # Check duplicate email
            cursor.execute("SELECT COUNT(*) FROM Passengers WHERE LOWER(email) = :1", [cleaned_email])
            if cursor.fetchone()[0] > 0:
                raise ValueError("An account with this email address already exists.")

            # Get next passenger_id from sequence
            next_p_id = get_next_sequence_val(cursor, "PASSENGER_SEQ")

            # Insert into Passengers
            insert_passenger_sql = """
                INSERT INTO Passengers (
                    passenger_id,
                    name,
                    email,
                    phone,
                    preferences
                ) VALUES (
                    :pid,
                    :name,
                    :email,
                    :phone,
                    :pref
                )
            """
            cursor.execute(
                insert_passenger_sql,
                {
                    "pid": next_p_id,
                    "name": name.strip(),
                    "email": cleaned_email,
                    "phone": phone.strip(),
                    "pref": prefs_str,
                },
            )

            # Insert into PASSENGER_AUTH
            insert_auth_sql = """
                INSERT INTO PASSENGER_AUTH (
                    passenger_id,
                    password_hash,
                    status,
                    created_at,
                    activated_at
                ) VALUES (
                    :pid,
                    :pwd_hash,
                    'ACTIVE',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
            """
            cursor.execute(
                insert_auth_sql,
                {
                    "pid": next_p_id,
                    "pwd_hash": pwd_hash,
                },
            )

        conn.commit()
        return {
            "passenger_id": next_p_id,
            "name": name.strip(),
            "email": cleaned_email,
            "status": "ACTIVE",
        }
    except Exception as e:
        conn.rollback()
        if isinstance(e, oracledb.DatabaseError):
            error_obj, = e.args
            raise RuntimeError(f"Registration failed: {error_obj.message}") from e
        raise e
    finally:
        conn.close()


def issue_passenger_activation_token(passenger_id: int, expiry_days: int = 7) -> str:
    """
    Issue a single-use cryptographically random activation token for an existing passenger.
    The raw token is returned to the administrator/caller; its SHA-256 hash is saved in Oracle.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cursor:
            # Check passenger exists
            cursor.execute("SELECT COUNT(*) FROM Passengers WHERE passenger_id = :1", [passenger_id])
            if cursor.fetchone()[0] == 0:
                raise ValueError(f"Passenger ID {passenger_id} does not exist.")

            merge_sql = """
                MERGE INTO PASSENGER_AUTH a
                USING (SELECT :pid AS passenger_id FROM DUAL) s
                ON (a.passenger_id = s.passenger_id)
                WHEN MATCHED THEN
                    UPDATE SET 
                        activation_token_hash = :tok_hash,
                        token_expires_at = CURRENT_TIMESTAMP + NUMTODSINTERVAL(:days, 'DAY'),
                        status = 'PENDING_ACTIVATION'
                WHEN NOT MATCHED THEN
                    INSERT (
                        passenger_id,
                        activation_token_hash,
                        token_expires_at,
                        status,
                        created_at
                    ) VALUES (
                        :pid,
                        :tok_hash,
                        CURRENT_TIMESTAMP + NUMTODSINTERVAL(:days, 'DAY'),
                        'PENDING_ACTIVATION',
                        CURRENT_TIMESTAMP
                    )
            """
            cursor.execute(
                merge_sql,
                {
                    "pid": passenger_id,
                    "tok_hash": token_hash,
                    "days": expiry_days,
                },
            )
        conn.commit()
        return raw_token
    except Exception as e:
        conn.rollback()
        if isinstance(e, oracledb.DatabaseError):
            error_obj, = e.args
            raise RuntimeError(f"Failed to issue activation token: {error_obj.message}") from e
        raise e
    finally:
        conn.close()


def claim_passenger_account(passenger_id: int, raw_token: str, new_password: str) -> bool:
    """
    Claim an existing passenger account using a valid activation token:
    1. Hashes raw_token with SHA-256.
    2. Verifies token match and expiration in PASSENGER_AUTH.
    3. Hashes new password with Argon2id.
    4. Sets status = 'ACTIVE' and clears the token.
    """
    if len(new_password) < 8:
        raise ValueError("Password must be at least 8 characters long.")

    token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
    pwd_hash = hash_password(new_password)

    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cursor:
            update_sql = """
                UPDATE PASSENGER_AUTH
                SET 
                    password_hash = :pwd_hash,
                    status = 'ACTIVE',
                    activation_token_hash = NULL,
                    token_expires_at = NULL,
                    activated_at = CURRENT_TIMESTAMP
                WHERE passenger_id = :pid
                  AND activation_token_hash = :tok_hash
                  AND (token_expires_at IS NULL OR token_expires_at > CURRENT_TIMESTAMP)
            """
            cursor.execute(
                update_sql,
                {
                    "pwd_hash": pwd_hash,
                    "pid": passenger_id,
                    "tok_hash": token_hash,
                },
            )
            if cursor.rowcount == 0:
                raise ValueError("Invalid or expired activation token. Please request a new activation code.")

        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        if isinstance(e, oracledb.DatabaseError):
            error_obj, = e.args
            raise RuntimeError(f"Account activation failed: {error_obj.message}") from e
        raise e
    finally:
        conn.close()


def update_passenger_last_login(passenger_id: int) -> None:
    """
    Record current timestamp as last_login for a passenger.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE PASSENGER_AUTH SET last_login = CURRENT_TIMESTAMP WHERE passenger_id = :1",
                [passenger_id],
            )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ====================================================================
# ADMINISTRATOR AUTHENTICATION
# ====================================================================

def get_admin_by_username(username_or_email: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve administrator details from ADMIN_USERS by username or email.
    """
    sql = """
        SELECT 
            admin_id,
            username,
            email,
            password_hash,
            full_name,
            role,
            status,
            TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI:SS') AS created_at,
            TO_CHAR(last_login, 'YYYY-MM-DD HH24:MI:SS') AS last_login
        FROM ADMIN_USERS
        WHERE LOWER(username) = LOWER(:val) OR LOWER(email) = LOWER(:val)
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, {"val": username_or_email.strip()})
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "admin_id": int(row[0]),
                "username": row[1],
                "email": row[2],
                "password_hash": row[3],
                "full_name": row[4],
                "role": row[5],
                "status": row[6],
                "created_at": row[7],
                "last_login": row[8],
            }
    finally:
        conn.close()


def update_admin_last_login(admin_id: int) -> None:
    """
    Record current timestamp as last_login for an administrator.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE ADMIN_USERS SET last_login = CURRENT_TIMESTAMP WHERE admin_id = :1",
                [admin_id],
            )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ====================================================================
# FLIGHT SEARCH & BOOKING (TRANSACTIONS WITH SEQUENCE GENERATION)
# ====================================================================

def search_flights(
    origin_airport_id: Optional[str] = None,
    destination_airport_id: Optional[str] = None,
    target_timezone: str = "Asia/Kolkata",
) -> List[Dict[str, Any]]:
    """
    Search available flights with accurate timezone conversion via Oracle's AT TIME ZONE.
    Returns clean dictionary records.
    """
    valid_tzs = ["Asia/Kolkata", "Asia/Dubai", "Europe/London", "America/New_York", "UTC", "Asia/Singapore"]
    tz_str = target_timezone if target_timezone in valid_tzs else "Asia/Kolkata"

    sql = f"""
        SELECT 
            f.flight_id,
            f.flight_no,
            f.flight_no AS flight_number,
            f.origin_id,
            f.origin_id AS origin_code,
            a1.name AS origin_name,
            a1.city AS origin_city,
            a1.country AS origin_country,
            f.destination_id,
            f.destination_id AS destination_code,
            a2.name AS destination_name,
            a2.city AS destination_city,
            a2.country AS destination_country,
            TO_CHAR(f.departure_time AT TIME ZONE '{tz_str}', 'YYYY-MM-DD HH24:MI:SS') AS departure_time_local,
            TO_CHAR(f.arrival_time AT TIME ZONE '{tz_str}', 'YYYY-MM-DD HH24:MI:SS') AS arrival_time_local,
            ROUND((CAST(f.arrival_time AS DATE) - CAST(f.departure_time AS DATE)) * 24, 2) AS duration_hours,
            f.fare,
            f.currency
        FROM Flights f
        JOIN Airports a1 ON f.origin_id = a1.airport_id
        JOIN Airports a2 ON f.destination_id = a2.airport_id
        WHERE 1=1
          AND (:orig_id IS NULL OR f.origin_id = :orig_id)
          AND (:dest_id IS NULL OR f.destination_id = :dest_id)
        ORDER BY f.departure_time ASC
    """
    params = {
        "orig_id": origin_airport_id if origin_airport_id and origin_airport_id != "All" else None,
        "dest_id": destination_airport_id if destination_airport_id and destination_airport_id != "All" else None,
    }
    df = fetch_df(sql, params)
    return df.to_dict(orient="records")


def book_flight(
    passenger_id: int,
    flight_id: int,
    special_request: str,
    payment_method: str,
    currency: str,
    fare_inr: float,
) -> Dict[str, Any]:
    """
    Perform flight booking and payment creation inside a single ACID transaction:
    1. Fetch next booking_id from BOOKING_SEQ.NEXTVAL (concurrency-safe)
    2. Fetch next payment_id from PAYMENT_SEQ.NEXTVAL (concurrency-safe)
    3. Compute payment amount based on currency (USD converted at 83 INR/USD)
    4. Insert into Bookings (status CONFIRMED, metadata as JSON string)
    5. Insert into Payments (status SUCCESS)
    6. COMMIT on success, ROLLBACK on any failure.
    """
    if currency == "USD":
        payment_amount = round(fare_inr / 83.0, 2)
    else:
        payment_amount = round(float(fare_inr), 2)

    metadata_json = json.dumps({"special": special_request})

    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cursor:
            # 1. Fetch next booking_id using sequence
            next_booking_id = get_next_sequence_val(cursor, "BOOKING_SEQ")

            # 2. Fetch next payment_id using sequence
            next_payment_id = get_next_sequence_val(cursor, "PAYMENT_SEQ")

            # 3. Insert into Bookings
            insert_booking_sql = """
                INSERT INTO Bookings (
                    booking_id,
                    passenger_id,
                    flight_id,
                    booking_date,
                    status,
                    metadata
                ) VALUES (
                    :b_id,
                    :p_id,
                    :f_id,
                    TRUNC(SYSDATE),
                    'CONFIRMED',
                    :meta
                )
            """
            cursor.execute(
                insert_booking_sql,
                {
                    "b_id": next_booking_id,
                    "p_id": passenger_id,
                    "f_id": flight_id,
                    "meta": metadata_json,
                },
            )

            # 4. Insert into Payments
            insert_payment_sql = """
                INSERT INTO Payments (
                    payment_id,
                    booking_id,
                    amount,
                    currency,
                    payment_method,
                    status,
                    payment_date
                ) VALUES (
                    :pay_id,
                    :b_id,
                    :amt,
                    :curr,
                    :method,
                    'SUCCESS',
                    TRUNC(SYSDATE)
                )
            """
            cursor.execute(
                insert_payment_sql,
                {
                    "pay_id": next_payment_id,
                    "b_id": next_booking_id,
                    "amt": payment_amount,
                    "curr": currency,
                    "method": payment_method,
                },
            )

        # 5. Commit both operations atomically
        conn.commit()
        return {
            "booking_id": next_booking_id,
            "payment_id": next_payment_id,
            "amount": payment_amount,
            "currency": currency,
            "status": "CONFIRMED",
        }
    except Exception as e:
        conn.rollback()
        if isinstance(e, oracledb.DatabaseError):
            error_obj, = e.args
            raise RuntimeError(f"Booking transaction failed: {error_obj.message}") from e
        raise RuntimeError(f"Booking transaction failed: {str(e)}") from e
    finally:
        conn.close()


def cancel_booking(booking_id: int) -> bool:
    """
    Cancel a booking by setting status to 'CANCELLED' and committing.
    Preserved for backward-compatibility with existing Streamlit app.
    """
    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE Bookings SET status = 'CANCELLED' WHERE booking_id = :1",
                [booking_id],
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Booking ID {booking_id} not found.")
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        if isinstance(e, oracledb.DatabaseError):
            error_obj, = e.args
            raise RuntimeError(f"Cancellation failed: {error_obj.message}") from e
        raise e
    finally:
        conn.close()


def get_passenger_bookings_history(passenger_id: int) -> List[Dict[str, Any]]:
    """
    Retrieve all booking records and associated payment details for a specific passenger.
    """
    sql = """
        SELECT 
            b.booking_id,
            TO_CHAR(b.booking_date, 'YYYY-MM-DD') AS booking_date,
            b.status AS booking_status,
            b.metadata,
            f.flight_id,
            f.flight_no,
            f.origin_id,
            a1.city AS origin_city,
            a1.name AS origin_name,
            f.destination_id,
            a2.city AS destination_city,
            a2.name AS destination_name,
            TO_CHAR(f.departure_time, 'YYYY-MM-DD HH24:MI:SS') AS departure_time,
            TO_CHAR(f.arrival_time, 'YYYY-MM-DD HH24:MI:SS') AS arrival_time,
            p.payment_id,
            p.amount,
            p.currency,
            p.payment_method,
            p.status AS payment_status
        FROM Bookings b
        JOIN Flights f ON b.flight_id = f.flight_id
        JOIN Airports a1 ON f.origin_id = a1.airport_id
        JOIN Airports a2 ON f.destination_id = a2.airport_id
        LEFT JOIN Payments p ON b.booking_id = p.booking_id
        WHERE b.passenger_id = :pid
        ORDER BY b.booking_id DESC
    """
    df = fetch_df(sql, {"pid": passenger_id})
    return df.to_dict(orient="records")


def cancel_passenger_booking(booking_id: int, passenger_id: int) -> bool:
    """
    Cancel an eligible booking for an authenticated passenger.
    Ensures ownership and prevents re-cancellation of cancelled bookings.
    """
    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM Bookings WHERE booking_id = :1 AND passenger_id = :2",
                [booking_id, passenger_id],
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("Booking not found or does not belong to you.")
            if row[0] == "CANCELLED":
                raise ValueError("This booking has already been cancelled.")

            cursor.execute(
                "UPDATE Bookings SET status = 'CANCELLED' WHERE booking_id = :1 AND passenger_id = :2",
                [booking_id, passenger_id],
            )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        if isinstance(e, oracledb.DatabaseError):
            error_obj, = e.args
            raise RuntimeError(f"Cancellation failed: {error_obj.message}") from e
        raise e
    finally:
        conn.close()


# ====================================================================
# ADMINISTRATOR RECORD MANAGEMENT (CRUD HELPERS)
# ====================================================================

def admin_get_airports() -> List[Dict[str, Any]]:
    sql = "SELECT airport_id, name, city, country, timezone FROM Airports ORDER BY airport_id"
    return fetch_df(sql).to_dict(orient="records")


def admin_create_airport(airport_id: str, name: str, city: str, country: str, timezone: str) -> Dict[str, Any]:
    code = airport_id.strip().upper()
    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO Airports (airport_id, name, city, country, timezone)
                VALUES (:id, :name, :city, :country, :tz)
                """,
                {
                    "id": code,
                    "name": name.strip(),
                    "city": city.strip(),
                    "country": country.strip(),
                    "tz": timezone.strip(),
                },
            )
        conn.commit()
        return {"airport_id": code, "name": name.strip()}
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def admin_update_airport(airport_id: str, name: str, city: str, country: str, timezone: str) -> bool:
    code = airport_id.strip().upper()
    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE Airports
                SET name = :name, city = :city, country = :country, timezone = :tz
                WHERE airport_id = :id
                """,
                {
                    "id": code,
                    "name": name.strip(),
                    "city": city.strip(),
                    "country": country.strip(),
                    "tz": timezone.strip(),
                },
            )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def admin_delete_airport(airport_id: str) -> bool:
    """
    Safely delete an airport only if no flights reference it.
    """
    code = airport_id.strip().upper()
    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM Flights WHERE origin_id = :1 OR destination_id = :1",
                [code],
            )
            flight_count = cursor.fetchone()[0]
            if flight_count > 0:
                raise ValueError(
                    f"Cannot delete airport '{code}': It is referenced by {flight_count} active flight(s)."
                )
            cursor.execute("DELETE FROM Airports WHERE airport_id = :1", [code])
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def admin_get_flights() -> List[Dict[str, Any]]:
    sql = """
        SELECT 
            f.flight_id,
            f.flight_no,
            f.origin_id,
            a1.city || ' (' || f.origin_id || ')' AS origin,
            f.destination_id,
            a2.city || ' (' || f.destination_id || ')' AS destination,
            TO_CHAR(f.departure_time, 'YYYY-MM-DD HH24:MI') AS departure_time,
            TO_CHAR(f.arrival_time, 'YYYY-MM-DD HH24:MI') AS arrival_time,
            f.fare,
            f.currency
        FROM Flights f
        JOIN Airports a1 ON f.origin_id = a1.airport_id
        JOIN Airports a2 ON f.destination_id = a2.airport_id
        ORDER BY f.flight_id
    """
    return fetch_df(sql).to_dict(orient="records")


def admin_create_flight(
    flight_no: str,
    origin_id: str,
    destination_id: str,
    departure_str: str,
    arrival_str: str,
    fare: float,
    currency: str = "INR",
) -> Dict[str, Any]:
    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT NVL(MAX(flight_id), 0) + 1 FROM Flights")
            next_id = int(cursor.fetchone()[0])
            insert_sql = """
                INSERT INTO Flights (
                    flight_id,
                    flight_no,
                    origin_id,
                    destination_id,
                    departure_time,
                    arrival_time,
                    fare,
                    currency
                ) VALUES (
                    :id,
                    :num,
                    :orig,
                    :dest,
                    TO_TIMESTAMP_TZ(:dep, 'YYYY-MM-DD HH24:MI:SS TZR'),
                    TO_TIMESTAMP_TZ(:arr, 'YYYY-MM-DD HH24:MI:SS TZR'),
                    :fare,
                    :curr
                )
            """
            cursor.execute(
                insert_sql,
                {
                    "id": next_id,
                    "num": flight_no.strip().upper(),
                    "orig": origin_id.strip().upper(),
                    "dest": destination_id.strip().upper(),
                    "dep": departure_str,
                    "arr": arrival_str,
                    "fare": fare,
                    "curr": currency,
                },
            )
        conn.commit()
        return {"flight_id": next_id, "flight_no": flight_no.strip().upper()}
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def admin_update_flight(flight_id: int, fare: float) -> bool:
    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE Flights SET fare = :fare WHERE flight_id = :id", {"fare": fare, "id": flight_id})
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def admin_get_passengers(search: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = """
        SELECT 
            p.passenger_id,
            p.name,
            p.email,
            p.phone,
            p.preferences,
            NVL(a.status, 'NO_ACCOUNT') AS auth_status,
            TO_CHAR(a.last_login, 'YYYY-MM-DD HH24:MI') AS last_login,
            COUNT(b.booking_id) AS total_bookings
        FROM Passengers p
        LEFT JOIN PASSENGER_AUTH a ON p.passenger_id = a.passenger_id
        LEFT JOIN Bookings b ON p.passenger_id = b.passenger_id
        WHERE (:s IS NULL OR LOWER(p.name || ' ' || p.email || ' ' || p.phone) LIKE '%' || LOWER(:s) || '%')
        GROUP BY 
            p.passenger_id, p.name, p.email, p.phone, p.preferences,
            a.status, a.last_login
        ORDER BY p.passenger_id
    """
    return fetch_df(sql, {"s": search.strip() if search else None}).to_dict(orient="records")


def admin_get_bookings(status: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = """
        SELECT 
            b.booking_id,
            b.passenger_id,
            p.name AS passenger_name,
            b.flight_id,
            f.flight_no,
            TO_CHAR(b.booking_date, 'YYYY-MM-DD') AS booking_date,
            b.status,
            b.metadata,
            pay.amount,
            pay.currency,
            pay.status AS payment_status
        FROM Bookings b
        JOIN Passengers p ON b.passenger_id = p.passenger_id
        JOIN Flights f ON b.flight_id = f.flight_id
        LEFT JOIN Payments pay ON b.booking_id = pay.booking_id
        WHERE (:st IS NULL OR b.status = :st)
        ORDER BY b.booking_id DESC
    """
    return fetch_df(sql, {"st": status}).to_dict(orient="records")


def admin_get_payments(status: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = """
        SELECT 
            pay.payment_id,
            pay.booking_id,
            pay.amount,
            pay.currency,
            pay.payment_method,
            pay.status,
            TO_CHAR(pay.payment_date, 'YYYY-MM-DD') AS payment_date
        FROM Payments pay
        WHERE (:st IS NULL OR pay.status = :st)
        ORDER BY pay.payment_id DESC
    """
    return fetch_df(sql, {"st": status}).to_dict(orient="records")


# ====================================================================
# ANALYTICS QUERIES & VIEW SQL TRANSPARENCY
# ====================================================================

SQL_EXPLANATIONS = {
    "kpis": {
        "title": "System-Wide Operations KPIs",
        "description": "Calculates primary airline metrics across bookings, revenue, and active flights using single-pass aggregations.",
        "sql": """
SELECT 
    (SELECT COUNT(*) FROM Bookings) AS total_bookings,
    (SELECT COUNT(*) FROM Bookings WHERE status = 'CONFIRMED') AS confirmed_bookings,
    (SELECT COUNT(*) FROM Bookings WHERE status = 'CANCELLED') AS cancelled_bookings,
    (SELECT NVL(SUM(amount), 0) FROM Payments WHERE status = 'SUCCESS' AND currency = 'INR') AS total_revenue_inr,
    (SELECT COUNT(*) FROM Passengers) AS total_passengers,
    (SELECT COUNT(*) FROM Flights) AS total_flights,
    (SELECT COUNT(DISTINCT origin_id || '-' || destination_id) FROM Flights) AS active_routes
FROM DUAL
        """,
    },
    "route_ranking": {
        "title": "Route Performance Ranking (RANK() OVER)",
        "description": "Applies the analytic function RANK() OVER (ORDER BY revenue DESC) to rank routes by total realized income.",
        "sql": """
SELECT 
    f.flight_no,
    a1.city || ' -> ' || a2.city AS route,
    COUNT(b.booking_id) AS total_bookings,
    SUM(p.amount) AS total_revenue,
    RANK() OVER (ORDER BY SUM(p.amount) DESC) AS revenue_rank
FROM Flights f
JOIN Airports a1 ON f.origin_id = a1.airport_id
JOIN Airports a2 ON f.destination_id = a2.airport_id
JOIN Bookings b ON f.flight_id = b.flight_id
JOIN Payments p ON b.booking_id = p.booking_id
WHERE p.status = 'SUCCESS'
GROUP BY f.flight_no, a1.city, a2.city
ORDER BY revenue_rank ASC
        """,
    },
    "day_over_day": {
        "title": "Day-over-Day Revenue Trends (LAG())",
        "description": "Uses LAG(daily_revenue, 1) OVER (ORDER BY payment_date) to compute day-over-day revenue differences and percentage growth.",
        "sql": """
SELECT 
    TO_CHAR(payment_date, 'YYYY-MM-DD') AS day,
    SUM(amount) AS daily_revenue,
    LAG(SUM(amount), 1) OVER (ORDER BY payment_date) AS prev_day_revenue,
    ROUND(
        (SUM(amount) - LAG(SUM(amount), 1) OVER (ORDER BY payment_date)) / 
        NULLIF(LAG(SUM(amount), 1) OVER (ORDER BY payment_date), 0) * 100, 
        2
    ) AS growth_pct
FROM Payments
WHERE status = 'SUCCESS' AND currency = 'INR'
GROUP BY payment_date
ORDER BY payment_date ASC
        """,
    },
    "cumulative_revenue": {
        "title": "Cumulative Revenue (SUM() OVER)",
        "description": "Computes running total revenue over time using SUM() OVER (ORDER BY payment_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW).",
        "sql": """
SELECT 
    TO_CHAR(payment_date, 'YYYY-MM-DD') AS payment_day,
    SUM(amount) AS daily_total,
    SUM(SUM(amount)) OVER (ORDER BY payment_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulative_total
FROM Payments
WHERE status = 'SUCCESS' AND currency = 'INR'
GROUP BY payment_date
ORDER BY payment_date ASC
        """,
    },
    "meal_preferences": {
        "title": "Passenger Preferences (JSON_VALUE)",
        "description": "Extracts passenger meal choices stored in JSON format using Oracle 23ai's JSON_VALUE operator.",
        "sql": """
SELECT 
    NVL(JSON_VALUE(preferences, '$.meal'), 'Not Specified') AS meal_choice,
    COUNT(*) AS count
FROM Passengers
GROUP BY JSON_VALUE(preferences, '$.meal')
ORDER BY count DESC
        """,
    },
    "route_revenue_mv": {
        "title": "Route Revenue Summary (Materialized View)",
        "description": "Reads directly from ROUTE_REVENUE_MV pre-aggregated table, refreshed on-demand with DBMS_MVIEW.REFRESH.",
        "sql": """
SELECT 
    flight_id,
    flight_number,
    route,
    total_bookings,
    confirmed_bookings,
    total_revenue
FROM ROUTE_REVENUE_MV
ORDER BY total_revenue DESC
        """,
    },
}


def get_admin_kpis() -> Dict[str, Any]:
    df = fetch_df(SQL_EXPLANATIONS["kpis"]["sql"])
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


def get_route_ranking() -> List[Dict[str, Any]]:
    return fetch_df(SQL_EXPLANATIONS["route_ranking"]["sql"]).to_dict(orient="records")


def get_day_over_day_revenue() -> List[Dict[str, Any]]:
    return fetch_df(SQL_EXPLANATIONS["day_over_day"]["sql"]).to_dict(orient="records")


def get_cumulative_revenue() -> List[Dict[str, Any]]:
    return fetch_df(SQL_EXPLANATIONS["cumulative_revenue"]["sql"]).to_dict(orient="records")


def get_passenger_meal_preferences() -> List[Dict[str, Any]]:
    return fetch_df(SQL_EXPLANATIONS["meal_preferences"]["sql"]).to_dict(orient="records")


def get_route_revenue_mv_data() -> List[Dict[str, Any]]:
    return fetch_df(SQL_EXPLANATIONS["route_revenue_mv"]["sql"]).to_dict(orient="records")
