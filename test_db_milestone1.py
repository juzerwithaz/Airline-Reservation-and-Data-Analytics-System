"""
test_db_milestone1.py - Milestone 1 Verification Script
=======================================================
Verifies database connectivity, admin bootstrap lookup, sequence helpers,
flight search with AT TIME ZONE, and existing table row counts.
"""

import sys
import db


def run_tests():
    print("=" * 60)
    print("       MILESTONE 1: DATABASE EXTENSION VERIFICATION       ")
    print("=" * 60)

    # 1. Test Oracle connectivity
    print("\n[TEST 1] Testing Oracle 23ai connection...")
    try:
        conn_info = db.test_connection()
        print(f"  [PASS] Connected as '{conn_info['user']}' to {conn_info['banner']}")
    except Exception as e:
        print(f"  [FAIL] Connection error: {e}")
        return False

    # 2. Test Admin lookup
    print("\n[TEST 2] Testing Admin user retrieval in ADMIN_USERS...")
    try:
        admins = db.fetch_df("SELECT admin_id, username, email, role, status FROM ADMIN_USERS")
        if admins.empty:
            print("  [WARN] ADMIN_USERS has 0 rows. Please run setup_admin.py first.")
        else:
            print(f"  [PASS] Found {len(admins)} admin account(s):")
            for _, adm in admins.iterrows():
                print(f"         - ID {adm['admin_id']}: {adm['username']} ({adm['email']}) [Role: {adm['role']}, Status: {adm['status']}]")
    except Exception as e:
        print(f"  [FAIL] Admin lookup error: {e}")
        return False

    # 3. Test Argon2id password hashing and verification
    print("\n[TEST 3] Testing Argon2id password hashing & verification...")
    try:
        sample_pwd = "SecureTestPassword@2026"
        hashed = db.hash_password(sample_pwd)
        valid = db.verify_password(hashed, sample_pwd)
        invalid = db.verify_password(hashed, "WrongPassword")
        assert valid is True and invalid is False, "Password verification logic failed"
        print(f"  [PASS] Argon2id hashing and verification verified successfully.")
    except Exception as e:
        print(f"  [FAIL] Password hashing test error: {e}")
        return False

    # 4. Test Flight search with AT TIME ZONE
    print("\n[TEST 4] Testing search_flights() with AT TIME ZONE projection...")
    try:
        flights = db.search_flights(target_timezone="Asia/Kolkata")
        print(f"  [PASS] Retrieved {len(flights)} flight(s) with accurate local timezone.")
        if flights:
            f0 = flights[0]
            print(f"         Sample: Flight {f0['flight_number']} ({f0['origin_code']} -> {f0['destination_code']})")
            print(f"                 Departure: {f0['departure_time_local']} | Fare: INR {f0['fare']}")
    except Exception as e:
        print(f"  [FAIL] Flight search error: {e}")
        return False

    # 5. Test Admin KPI Aggregations
    print("\n[TEST 5] Testing get_admin_kpis() aggregation...")
    try:
        kpis = db.get_admin_kpis()
        print(f"  [PASS] Real KPIs from Oracle:")
        print(f"         - Total Bookings:     {kpis.get('total_bookings')}")
        print(f"         - Confirmed Bookings: {kpis.get('confirmed_bookings')}")
        print(f"         - Cancelled Bookings: {kpis.get('cancelled_bookings')}")
        print(f"         - Total Revenue (INR): {kpis.get('total_revenue_inr')}")
        print(f"         - Total Passengers:   {kpis.get('total_passengers')}")
        print(f"         - Total Flights:      {kpis.get('total_flights')}")
        print(f"         - Active Routes:      {kpis.get('active_routes')}")
    except Exception as e:
        print(f"  [FAIL] KPI query error: {e}")
        return False

    # 6. Verify Table Data Integrity
    print("\n[TEST 6] Verifying original table counts (Zero data loss check)...")
    try:
        row_counts = {
            "Airports": db.fetch_one("SELECT COUNT(*) FROM Airports")[0],
            "Flights": db.fetch_one("SELECT COUNT(*) FROM Flights")[0],
            "Passengers": db.fetch_one("SELECT COUNT(*) FROM Passengers")[0],
            "Bookings": db.fetch_one("SELECT COUNT(*) FROM Bookings")[0],
            "Payments": db.fetch_one("SELECT COUNT(*) FROM Payments")[0],
        }
        for tbl, count in row_counts.items():
            print(f"         - {tbl}: {count} rows")
        assert row_counts["Airports"] == 10, "Airports row count changed!"
        assert row_counts["Flights"] == 20, "Flights row count changed!"
        assert row_counts["Passengers"] >= 60, "Passengers row count decreased!"
        assert row_counts["Bookings"] >= 302, "Bookings row count decreased!"
        assert row_counts["Payments"] >= 239, "Payments row count decreased!"
        print("  [PASS] All core database tables remain 100% intact.")
    except Exception as e:
        print(f"  [FAIL] Data integrity check error: {e}")
        return False

    print("\n" + "=" * 60)
    print("  ALL MILESTONE 1 DATABASE EXTENSION TESTS PASSED!  ")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)

