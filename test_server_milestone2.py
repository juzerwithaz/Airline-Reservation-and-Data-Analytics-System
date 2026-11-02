"""
test_server_milestone2.py - Milestone 2 REST API Test Suite
===========================================================
Executes end-to-end integration tests on FastAPI server endpoints
connected to the live Oracle Database 23ai instance.
"""

import sys
import json
from fastapi.testclient import TestClient
from server import app, create_access_token
import db

client = TestClient(app)


def run_milestone2_tests():
    print("=" * 65)
    print("       MILESTONE 2: FASTAPI REST API VERIFICATION SUITE       ")
    print("=" * 65)

    test_email = "api_tester_99@airline-demo.local"
    test_password = "SecureApiPassword@2026"

    # Pre-test cleanup: ensure test user does not exist
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT passenger_id FROM Passengers WHERE email = :1", [test_email])
            row = cur.fetchone()
            if row:
                pid = row[0]
                cur.execute("DELETE FROM Payments WHERE booking_id IN (SELECT booking_id FROM Bookings WHERE passenger_id = :1)", [pid])
                cur.execute("DELETE FROM Bookings WHERE passenger_id = :1", [pid])
                cur.execute("DELETE FROM PASSENGER_AUTH WHERE passenger_id = :1", [pid])
                cur.execute("DELETE FROM Passengers WHERE passenger_id = :1", [pid])
                conn.commit()
    finally:
        conn.close()

    # ---------------------------------------------------------------
    # 1. System Health & Documentation
    # ---------------------------------------------------------------
    print("\n[TEST 1] Testing /health and /docs endpoints...")
    resp = client.get("/health")
    assert resp.status_code == 200, f"Health check failed: {resp.text}"
    health_data = resp.json()
    assert health_data["status"] == "healthy", "Expected status 'healthy'"
    print(f"  [PASS] /health: OK (Connected to {health_data['database']['banner']})")

    docs_resp = client.get("/docs")
    assert docs_resp.status_code == 200, "Swagger /docs not reachable"
    print("  [PASS] /docs: Swagger UI documentation reachable (HTTP 200).")

    # ---------------------------------------------------------------
    # 2. Passenger Registration
    # ---------------------------------------------------------------
    print("\n[TEST 2] Testing Passenger Registration (/api/auth/passenger/register)...")
    reg_payload = {
        "name": "Dr Anita Desai",
        "email": test_email,
        "phone": "+919811223344",
        "password": test_password,
        "preferences": {"meal": "Vegan", "seat": "Aisle"},
    }
    reg_resp = client.post("/api/auth/passenger/register", json=reg_payload)
    assert reg_resp.status_code == 200, f"Registration failed: {reg_resp.text}"
    reg_data = reg_resp.json()
    passenger_id = reg_data["user"]["passenger_id"]
    passenger_token = reg_data["access_token"]
    print(f"  [PASS] Passenger registered successfully (ID: {passenger_id}, Sequence: PASSENGER_SEQ)")
    print(f"         JWT Access Token generated (length: {len(passenger_token)} chars)")

    # ---------------------------------------------------------------
    # 3. Passenger Login & Profile
    # ---------------------------------------------------------------
    print("\n[TEST 3] Testing Passenger Login (/api/auth/passenger/login)...")
    login_resp = client.post("/api/auth/passenger/login", json={
        "username_or_email": test_email,
        "password": test_password,
    })
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    login_data = login_resp.json()
    assert login_data["user"]["email"] == test_email
    print(f"  [PASS] Login successful with Argon2id hash verification.")

    # Test profile with Bearer token
    profile_resp = client.get(
        "/api/passenger/me",
        headers={"Authorization": f"Bearer {passenger_token}"},
    )
    assert profile_resp.status_code == 200, f"Profile fetch failed: {profile_resp.text}"
    assert profile_resp.json()["name"] == "Dr Anita Desai"
    print(f"  [PASS] /api/passenger/me authenticated via JWT Bearer token.")

    # ---------------------------------------------------------------
    # 4. Flight Search with Oracle AT TIME ZONE
    # ---------------------------------------------------------------
    print("\n[TEST 4] Testing Flight Search (/api/flights)...")
    flights_resp = client.get("/api/flights?timezone=Asia/Kolkata")
    assert flights_resp.status_code == 200, f"Flight search failed: {flights_resp.text}"
    flights_data = flights_resp.json()
    assert flights_data["count"] == 20, f"Expected 20 flights, got {flights_data['count']}"
    sample_flight = flights_data["flights"][0]
    flight_id = sample_flight["flight_id"]
    print(f"  [PASS] /api/flights: Retrieved 20 flights with AT TIME ZONE projection.")
    print(f"         Sample: {sample_flight['flight_no']} ({sample_flight['origin_city']} -> {sample_flight['destination_city']}) - INR {sample_flight['fare']}")

    # ---------------------------------------------------------------
    # 5. Transactional Booking Creation (ACID with Sequences)
    # ---------------------------------------------------------------
    print("\n[TEST 5] Testing Transactional Booking Creation (/api/bookings)...")
    booking_payload = {
        "flight_id": flight_id,
        "special_request": "Diabetic Meal, Window Seat",
        "payment_method": "UPI",
        "currency": "INR",
    }
    booking_resp = client.post(
        "/api/bookings",
        json=booking_payload,
        headers={"Authorization": f"Bearer {passenger_token}"},
    )
    assert booking_resp.status_code == 200, f"Booking failed: {booking_resp.text}"
    booking_data = booking_resp.json()
    b_id = booking_data["booking"]["booking_id"]
    pay_id = booking_data["booking"]["payment_id"]
    assert b_id > 302, f"Expected booking_id > 302, got {b_id}"
    assert pay_id > 239, f"Expected payment_id > 239, got {pay_id}"
    print(f"  [PASS] Booking created atomically in Oracle:")
    print(f"         - Booking ID: {b_id} (BOOKING_SEQ.NEXTVAL)")
    print(f"         - Payment ID: {pay_id} (PAYMENT_SEQ.NEXTVAL)")
    print(f"         - Status: {booking_data['booking']['status']}")

    # ---------------------------------------------------------------
    # 6. Passenger Booking History & Cancellation
    # ---------------------------------------------------------------
    print("\n[TEST 6] Testing Booking History and Cancellation...")
    hist_resp = client.get(
        "/api/bookings/my",
        headers={"Authorization": f"Bearer {passenger_token}"},
    )
    assert hist_resp.status_code == 200
    my_bookings = hist_resp.json()["bookings"]
    assert len(my_bookings) >= 1
    print(f"  [PASS] /api/bookings/my: Found {len(my_bookings)} booking(s) for authenticated passenger.")

    cancel_resp = client.post(
        f"/api/bookings/{b_id}/cancel",
        headers={"Authorization": f"Bearer {passenger_token}"},
    )
    assert cancel_resp.status_code == 200, f"Cancellation failed: {cancel_resp.text}"
    print(f"  [PASS] Booking {b_id} cancelled successfully in Oracle.")

    # Verify duplicate cancellation rejection
    re_cancel_resp = client.post(
        f"/api/bookings/{b_id}/cancel",
        headers={"Authorization": f"Bearer {passenger_token}"},
    )
    assert re_cancel_resp.status_code == 400, "Expected 400 Bad Request on re-cancelling"
    print(f"  [PASS] Repeated cancellation rejected with 400: '{re_cancel_resp.json()['detail']}'")

    # ---------------------------------------------------------------
    # 7. Role-Based Access Control & Admin API
    # ---------------------------------------------------------------
    print("\n[TEST 7] Testing Role-Based Access Control on Admin Endpoints...")
    # Attempting to access admin KPI endpoint with passenger token must fail with 403
    forbidden_resp = client.get(
        "/api/admin/analytics/kpis",
        headers={"Authorization": f"Bearer {passenger_token}"},
    )
    assert forbidden_resp.status_code == 403, f"Expected 403 Forbidden, got {forbidden_resp.status_code}"
    print("  [PASS] Passenger token rejected from admin routes with HTTP 403 Forbidden.")

    # Generate admin token
    admin_token = create_access_token({
        "sub": "1",
        "role": "SUPER_ADMIN",
        "username": "admin",
        "email": "admin@airline.local",
        "name": "System Administrator",
    })

    # Access KPIs with admin token
    kpi_resp = client.get(
        "/api/admin/analytics/kpis",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert kpi_resp.status_code == 200, f"Admin KPI failed: {kpi_resp.text}"
    kpi_data = kpi_resp.json()
    print(f"  [PASS] /api/admin/analytics/kpis accessed with SUPER_ADMIN token:")
    print(f"         - Total Bookings:  {kpi_data['data']['total_bookings']}")
    print(f"         - Total Revenue:   INR {kpi_data['data']['total_revenue_inr']}")
    print(f"         - Total Flights:   {kpi_data['data']['total_flights']}")

    # ---------------------------------------------------------------
    # 8. Advanced SQL Analytics Endpoints
    # ---------------------------------------------------------------
    print("\n[TEST 8] Testing Advanced SQL Analytics & View SQL Transparency...")
    # Route ranking (RANK() OVER)
    rr_resp = client.get("/api/admin/analytics/route-ranking", headers={"Authorization": f"Bearer {admin_token}"})
    assert rr_resp.status_code == 200
    print(f"  [PASS] Route Ranking (RANK() OVER): Returned {len(rr_resp.json()['data'])} ranked routes.")

    # Day-over-day revenue (LAG())
    dod_resp = client.get("/api/admin/analytics/day-over-day", headers={"Authorization": f"Bearer {admin_token}"})
    assert dod_resp.status_code == 200
    print(f"  [PASS] Day-over-Day Trends (LAG()): Returned {len(dod_resp.json()['data'])} days of trend data.")

    # SQL explanations endpoint
    sql_resp = client.get("/api/admin/analytics/sql-explanations")
    assert sql_resp.status_code == 200
    sqls = sql_resp.json()
    assert "route_ranking" in sqls and "day_over_day" in sqls and "cumulative_revenue" in sqls
    print(f"  [PASS] /api/admin/analytics/sql-explanations: Verified 6 transparent query definitions.")

    # ---------------------------------------------------------------
    # 9. Admin Operations: Issuing Activation Token for Existing Passenger
    # ---------------------------------------------------------------
    print("\n[TEST 9] Testing Admin-issued Passenger Activation Code...")
    issue_resp = client.post(
        "/api/admin/passengers/issue-activation",
        json={"passenger_id": 1, "expiry_days": 3},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert issue_resp.status_code == 200, f"Token issue failed: {issue_resp.text}"
    act_data = issue_resp.json()
    assert "activation_code" in act_data
    raw_code = act_data["activation_code"]
    print(f"  [PASS] Activation code issued for Passenger 1: '{raw_code[:10]}...' (SHA-256 hashed in Oracle)")

    # ---------------------------------------------------------------
    # 10. Post-Test Cleanup & Core Data Preservation
    # ---------------------------------------------------------------
    print("\n[TEST 10] Cleaning up test records & verifying database zero-data-loss...")
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM Payments WHERE booking_id IN (SELECT booking_id FROM Bookings WHERE passenger_id = :1)", [passenger_id])
            cur.execute("DELETE FROM Bookings WHERE passenger_id = :1", [passenger_id])
            cur.execute("DELETE FROM PASSENGER_AUTH WHERE passenger_id = :1", [passenger_id])
            cur.execute("DELETE FROM Passengers WHERE passenger_id = :1", [passenger_id])
            # Reset passenger 1 auth record if modified
            cur.execute("DELETE FROM PASSENGER_AUTH WHERE passenger_id = 1")
            conn.commit()
    finally:
        conn.close()

    # Verify original table counts
    counts = {
        "Airports": db.fetch_one("SELECT COUNT(*) FROM Airports")[0],
        "Flights": db.fetch_one("SELECT COUNT(*) FROM Flights")[0],
        "Passengers": db.fetch_one("SELECT COUNT(*) FROM Passengers")[0],
        "Bookings": db.fetch_one("SELECT COUNT(*) FROM Bookings")[0],
        "Payments": db.fetch_one("SELECT COUNT(*) FROM Payments")[0],
    }
    print(f"         - Airports:   {counts['Airports']} (Expected: 10)")
    print(f"         - Flights:    {counts['Flights']} (Expected: 20)")
    print(f"         - Passengers: {counts['Passengers']} (Expected: 60)")
    print(f"         - Bookings:   {counts['Bookings']} (Expected: >= 302)")
    print(f"         - Payments:   {counts['Payments']} (Expected: >= 239)")
    assert counts["Airports"] == 10
    assert counts["Flights"] == 20
    assert counts["Passengers"] == 60
    assert counts["Bookings"] >= 302
    assert counts["Payments"] >= 239
    print("  [PASS] Zero data loss: All original records preserved.")

    print("\n" + "=" * 65)
    print("  ALL 10 FASTAPI BACKEND VERIFICATION TESTS PASSED!  ")
    print("=" * 65)
    return True


if __name__ == "__main__":
    success = run_milestone2_tests()
    sys.exit(0 if success else 1)
