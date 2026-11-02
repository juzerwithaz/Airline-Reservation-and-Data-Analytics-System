import os
import json
from typing import Any, Dict, List, Optional, Tuple
import oracledb
import pandas as pd
from dotenv import load_dotenv

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
    1. Determine next booking_id = MAX(booking_id) + 1
    2. Determine next payment_id = MAX(payment_id) + 1
    3. Compute payment amount based on currency (if USD, convert at 83 INR/USD)
    4. Insert into Bookings (status CONFIRMED, metadata as JSON string)
    5. Insert into Payments (status SUCCESS)
    6. COMMIT on success, ROLLBACK on any failure.
    """
    # Currency conversion rate as specified in prompt: 83 INR per USD
    if currency == "USD":
        payment_amount = round(fare_inr / 83.0, 2)
    else:
        payment_amount = round(float(fare_inr), 2)

    metadata_json = json.dumps({"special": special_request})

    conn = get_connection()
    conn.autocommit = False  # Ensure single transaction control
    try:
        with conn.cursor() as cursor:
            # 1. Fetch next booking_id
            cursor.execute("SELECT NVL(MAX(booking_id), 0) + 1 FROM Bookings")
            next_booking_id = int(cursor.fetchone()[0])

            # 2. Fetch next payment_id
            cursor.execute("SELECT NVL(MAX(payment_id), 0) + 1 FROM Payments")
            next_payment_id = int(cursor.fetchone()[0])

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

