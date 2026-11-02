import os
from datetime import datetime
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import db

# Page Configuration
st.set_page_config(
    page_title="Airline Reservation and Booking Analytics System",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling for polished look
st.markdown(
    """
    <style>
        .main-header {
            font-size: 2.2rem;
            font-weight: 700;
            color: #1E3A8A;
            margin-bottom: 0.2rem;
        }
        .sub-header {
            font-size: 1.05rem;
            color: #4B5563;
            margin-bottom: 1.5rem;
        }
        .metric-card {
            background-color: #F8FAFC;
            border-radius: 10px;
            padding: 1.2rem;
            border: 1px solid #E2E8F0;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
        .stButton>button {
            border-radius: 8px;
            font-weight: 600;
        }
        .sql-box {
            background-color: #0F172A;
            color: #38BDF8;
            padding: 1rem;
            border-radius: 8px;
            font-family: monospace;
            font-size: 0.9rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def format_inr(val) -> str:
    """Format numeric values into standard Indian Rupee notation."""
    if val is None or pd.isna(val):
        return "₹0.00"
    return f"₹{float(val):,.2f}"


# -------------------------------------------------------------
# Cached Database Query Helpers (TTL: 30 seconds)
# -------------------------------------------------------------
@st.cache_data(ttl=30)
def get_kpis():
    confirmed = db.fetch_one("SELECT count(*) FROM Bookings WHERE status = 'CONFIRMED'")[0]
    total_rev = db.fetch_one(
        "SELECT ROUND(SUM(CASE WHEN currency = 'USD' THEN amount * 83 ELSE amount END), 2) "
        "FROM Payments WHERE status = 'SUCCESS'"
    )[0] or 0.0
    cancelled = db.fetch_one("SELECT count(*) FROM Bookings WHERE status = 'CANCELLED'")[0]
    routes_count = db.fetch_one("SELECT count(DISTINCT origin_id || '-' || destination_id) FROM Flights")[0]
    return confirmed, total_rev, cancelled, routes_count


@st.cache_data(ttl=30)
def get_route_revenue():
    sql = """
        SELECT
            origin_id,
            destination_id,
            origin_id || ' -> ' || destination_id AS route,
            bookings,
            total_revenue,
            RANK() OVER (ORDER BY total_revenue DESC) AS revenue_rank
        FROM route_revenue_mv
        ORDER BY revenue_rank ASC
    """
    return db.fetch_df(sql)


@st.cache_data(ttl=30)
def get_daily_revenue():
    sql = """
        SELECT
            booking_day,
            daily_revenue,
            LAG(daily_revenue) OVER (ORDER BY booking_day) AS prev_day_revenue,
            ROUND(daily_revenue - LAG(daily_revenue) OVER (ORDER BY booking_day), 2) AS daily_change,
            SUM(daily_revenue) OVER (
                ORDER BY booking_day 
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS running_revenue
        FROM daily_revenue_v
        ORDER BY booking_day ASC
    """
    return db.fetch_df(sql)


@st.cache_data(ttl=30)
def get_airports():
    return db.fetch_df("SELECT airport_id, name, city, country, timezone FROM Airports ORDER BY city ASC")


@st.cache_data(ttl=30)
def search_flights(origin_id, destination_id, target_tz):
    # Whitelist valid timezones to prevent arbitrary input
    valid_tzs = ["Asia/Kolkata", "Asia/Dubai", "Europe/London", "America/New_York"]
    tz_str = target_tz if target_tz in valid_tzs else "Asia/Kolkata"

    # Use TO_CHAR with AT TIME ZONE for safe string transmission in thin mode
    sql = f"""
        SELECT
            f.flight_id,
            f.flight_no,
            f.origin_id,
            f.destination_id,
            a1.city AS origin_city,
            a2.city AS destination_city,
            f.fare,
            f.currency,
            TO_CHAR(f.departure_time AT TIME ZONE '{tz_str}', 'YYYY-MM-DD HH24:MI:SS') AS local_departure,
            TO_CHAR(f.arrival_time AT TIME ZONE '{tz_str}', 'YYYY-MM-DD HH24:MI:SS') AS local_arrival
        FROM Flights f
        JOIN Airports a1 ON f.origin_id = a1.airport_id
        JOIN Airports a2 ON f.destination_id = a2.airport_id
        WHERE (:orig IS NULL OR f.origin_id = :orig)
          AND (:dest IS NULL OR f.destination_id = :dest)
        ORDER BY f.departure_time ASC
    """
    params = {
        "orig": origin_id if origin_id != "All" else None,
        "dest": destination_id if destination_id != "All" else None,
    }
    return db.fetch_df(sql, params)


@st.cache_data(ttl=30)
def get_passengers_list():
    return db.fetch_df("SELECT passenger_id, name, email FROM Passengers ORDER BY name ASC")


@st.cache_data(ttl=30)
def get_all_flights_for_booking():
    sql = """
        SELECT
            f.flight_id,
            f.flight_no,
            f.origin_id || ' -> ' || f.destination_id AS route,
            a1.city || ' to ' || a2.city AS city_route,
            f.fare,
            f.currency
        FROM Flights f
        JOIN Airports a1 ON f.origin_id = a1.airport_id
        JOIN Airports a2 ON f.destination_id = a2.airport_id
        ORDER BY f.flight_no ASC
    """
    return db.fetch_df(sql)


@st.cache_data(ttl=30)
def get_bookings_table():
    sql = """
        SELECT
            booking_id,
            passenger,
            flight_no,
            origin_id,
            destination_id,
            origin_id || ' -> ' || destination_id AS route,
            fare,
            status,
            booking_date
        FROM booking_details_v
        ORDER BY booking_id DESC
    """
    return db.fetch_df(sql)


@st.cache_data(ttl=30)
def get_passengers_with_json():
    sql = """
        SELECT
            passenger_id,
            name,
            email,
            phone,
            NVL(JSON_VALUE(preferences, '$.meal'), 'Not Specified') AS meal,
            NVL(JSON_VALUE(preferences, '$.seat'), 'Not Specified') AS seat,
            NVL(JSON_VALUE(preferences, '$.baggage' RETURNING NUMBER), 0) AS baggage
        FROM Passengers
        ORDER BY passenger_id ASC
    """
    return db.fetch_df(sql)


@st.cache_data(ttl=30)
def get_meal_stats():
    sql = """
        SELECT
            NVL(JSON_VALUE(preferences, '$.meal'), 'Not Specified') AS meal_preference,
            COUNT(*) AS passenger_count
        FROM Passengers
        GROUP BY JSON_VALUE(preferences, '$.meal')
        ORDER BY passenger_count DESC
    """
    return db.fetch_df(sql)


@st.cache_data(ttl=30)
def get_payment_methods_analytics():
    sql = """
        SELECT
            payment_method,
            COUNT(*) AS total_transactions,
            ROUND(SUM(CASE WHEN currency = 'USD' THEN amount * 83 ELSE amount END), 2) AS total_revenue_inr,
            ROUND(AVG(CASE WHEN currency = 'USD' THEN amount * 83 ELSE amount END), 2) AS avg_transaction_inr
        FROM Payments
        WHERE status = 'SUCCESS'
        GROUP BY payment_method
        HAVING COUNT(*) > 10
        ORDER BY total_revenue_inr DESC
    """
    return db.fetch_df(sql)


@st.cache_data(ttl=30)
def get_currency_analytics():
    sql = """
        SELECT
            currency,
            COUNT(*) AS payment_count,
            ROUND(SUM(amount), 2) AS original_amount_sum,
            ROUND(SUM(CASE WHEN currency = 'USD' THEN amount * 83 ELSE amount END), 2) AS inr_equivalent_sum,
            ROUND(AVG(CASE WHEN currency = 'USD' THEN amount * 83 ELSE amount END), 2) AS avg_inr_equivalent
        FROM Payments
        WHERE status = 'SUCCESS'
        GROUP BY currency
        ORDER BY currency ASC
    """
    return db.fetch_df(sql)


@st.cache_data(ttl=30)
def get_fare_class_analytics():
    sql = """
        SELECT
            fare_class,
            COUNT(*) AS booking_count,
            ROUND(SUM(fare_inr), 2) AS total_fare_revenue
        FROM (
            SELECT
                b.booking_id,
                f.fare AS fare_inr,
                CASE
                    WHEN f.fare < 5000 THEN 'Budget (< ₹5,000)'
                    WHEN f.fare <= 25000 THEN 'Standard (₹5,000 - ₹25,000)'
                    ELSE 'Premium (> ₹25,000)'
                END AS fare_class
            FROM Bookings b
            JOIN Flights f ON b.flight_id = f.flight_id
            WHERE b.status = 'CONFIRMED'
        )
        GROUP BY fare_class
        ORDER BY total_fare_revenue DESC
    """
    return db.fetch_df(sql)


# -------------------------------------------------------------
# Sidebar Navigation & Database Status
# -------------------------------------------------------------
st.sidebar.markdown("## ✈️ Airline Management")
st.sidebar.caption("Oracle 23ai Database Powered")

# Connectivity check
try:
    status_info = db.test_connection()
    st.sidebar.success(f"🟢 Connected ({status_info['user']})")
except Exception as e:
    st.sidebar.error("🔴 Disconnected")
    st.error(f"Database Connection Error: {e}")

page = st.sidebar.radio(
    "Navigation",
    [
        "📊 Dashboard",
        "✈️ Search and Book",
        "📋 Bookings",
        "👤 Passengers (JSON)",
        "📈 Analytics",
    ],
    index=0,
)




# =============================================================
# PAGE 1: DASHBOARD
# =============================================================
if page == "📊 Dashboard":
    st.markdown('<div class="main-header">Airline Reservation & Analytics Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Real-time overview of bookings, revenue performance, and route popularity</div>', unsafe_allow_html=True)

    # Top KPI Metrics
    try:
        confirmed_count, total_revenue, cancelled_count, routes_count = get_kpis()
    except Exception as e:
        st.error(f"Failed to fetch KPIs: {e}")
        confirmed_count, total_revenue, cancelled_count, routes_count = 0, 0, 0, 0

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Confirmed Bookings", f"{confirmed_count:,}")
    with col2:
        st.metric("Total Revenue (INR)", format_inr(total_revenue))
    with col3:
        st.metric("Cancelled Bookings", f"{cancelled_count:,}")
    with col4:
        st.metric("Active Flight Routes", f"{routes_count}")

    st.markdown("---")

    # Materialized View Controls
    top_mv_col1, top_mv_col2 = st.columns([3, 1])
    with top_mv_col1:
        st.subheader("Route Revenue Rankings (Materialized View)")
        st.caption("Powered by `ROUTE_REVENUE_MV` using `RANK() OVER (ORDER BY total_revenue DESC)`")
    with top_mv_col2:
        if st.button("🔄 Refresh Materialized View", use_container_width=True):
            try:
                db.refresh_route_revenue_mv()
                st.cache_data.clear()
                st.success("Refreshed ROUTE_REVENUE_MV via DBMS_MVIEW.REFRESH!")
                st.rerun()
            except Exception as e:
                st.error(f"Refresh failed: {e}")

    try:
        df_routes = get_route_revenue()
        if not df_routes.empty:
            chart_col, table_col = st.columns([1.2, 1])
            with chart_col:
                # Plotly horizontal bar chart of top routes
                fig_routes = px.bar(
                    df_routes.sort_values(by="total_revenue", ascending=True),
                    x="total_revenue",
                    y="route",
                    orientation="h",
                    title="Revenue by Flight Route (INR)",
                    labels={"total_revenue": "Total Revenue (₹)", "route": "Route"},
                    text_auto=".2s",
                    color="total_revenue",
                    color_continuous_scale="Blues",
                )
                fig_routes.update_layout(showlegend=False, height=450, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig_routes, use_container_width=True)

            with table_col:
                df_display_routes = df_routes.copy()
                df_display_routes["total_revenue"] = df_display_routes["total_revenue"].apply(format_inr)
                df_display_routes = df_display_routes.rename(
                    columns={
                        "revenue_rank": "Rank",
                        "route": "Route",
                        "origin_id": "Origin",
                        "destination_id": "Destination",
                        "bookings": "Bookings",
                        "total_revenue": "Total Revenue",
                    }
                )
                st.dataframe(
                    df_display_routes[["Rank", "Route", "Bookings", "Total Revenue"]],
                    use_container_width=True,
                    height=450,
                    hide_index=True,
                )
        else:
            st.info("No route data found in ROUTE_REVENUE_MV.")
    except Exception as e:
        st.error(f"Error loading route revenue: {e}")

    st.markdown("---")

    # Daily Revenue & Trend Analysis
    st.subheader("Daily Revenue Trends & Cumulative Performance")
    st.caption("Demonstrating `LAG()` for day-over-day changes and `SUM() OVER` for running cumulative revenue")

    try:
        df_daily = get_daily_revenue()
        if not df_daily.empty:
            # Convert date to string for clean plotting
            df_daily["day_str"] = pd.to_datetime(df_daily["booking_day"]).dt.strftime("%Y-%m-%d")

            # Dual-line chart using Plotly
            fig_daily = go.Figure()
            fig_daily.add_trace(
                go.Bar(
                    x=df_daily["day_str"],
                    y=df_daily["daily_revenue"],
                    name="Daily Revenue",
                    marker_color="#3B82F6",
                    opacity=0.7,
                )
            )
            fig_daily.add_trace(
                go.Scatter(
                    x=df_daily["day_str"],
                    y=df_daily["running_revenue"],
                    name="Cumulative Running Total",
                    mode="lines+markers",
                    yaxis="y2",
                    line=dict(color="#10B981", width=3),
                )
            )
            fig_daily.update_layout(
                title="Daily Revenue & Running Total Over Time",
                xaxis=dict(title="Booking Date"),
                yaxis=dict(title="Daily Revenue (₹)"),
                yaxis2=dict(title="Running Total (₹)", overlaying="y", side="right"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                height=450,
                margin=dict(l=20, r=20, t=40, b=20),
            )
            st.plotly_chart(fig_daily, use_container_width=True)

            with st.expander("📋 View Daily Breakdown Data Table"):
                df_daily_view = df_daily.copy()
                df_daily_view["daily_revenue"] = df_daily_view["daily_revenue"].apply(format_inr)
                df_daily_view["prev_day_revenue"] = df_daily_view["prev_day_revenue"].apply(format_inr)
                df_daily_view["daily_change"] = df_daily_view["daily_change"].apply(
                    lambda x: f"+{format_inr(x)}" if (x is not None and x > 0) else format_inr(x)
                )
                df_daily_view["running_revenue"] = df_daily_view["running_revenue"].apply(format_inr)
                df_daily_view = df_daily_view.rename(
                    columns={
                        "day_str": "Date",
                        "daily_revenue": "Daily Revenue",
                        "prev_day_revenue": "Previous Day Revenue (LAG)",
                        "daily_change": "Day-over-Day Change",
                        "running_revenue": "Running Total (SUM OVER)",
                    }
                )
                st.dataframe(
                    df_daily_view[["Date", "Daily Revenue", "Previous Day Revenue (LAG)", "Day-over-Day Change", "Running Total (SUM OVER)"]],
                    use_container_width=True,
                    hide_index=True,
                )
    except Exception as e:
        st.error(f"Error loading daily revenue: {e}")

    # View SQL Expander
    with st.expander("🔍 View SQL (Dashboard Features)"):
        st.markdown(
            """
            **1. Materialized View Definition & Route Ranking (RANK Analytic Function)**
            ```sql
            -- Materialized View definition:
            CREATE MATERIALIZED VIEW route_revenue_mv
            BUILD IMMEDIATE REFRESH COMPLETE ON DEMAND AS
            SELECT
                f.origin_id,
                f.destination_id,
                COUNT(b.booking_id) AS bookings,
                ROUND(SUM(CASE WHEN p.currency = 'USD' THEN p.amount * 83 ELSE p.amount END), 2) AS total_revenue
            FROM Bookings b
            JOIN Flights f ON b.flight_id = f.flight_id
            JOIN Payments p ON b.booking_id = p.booking_id
            WHERE b.status = 'CONFIRMED' AND p.status = 'SUCCESS'
            GROUP BY f.origin_id, f.destination_id;

            -- Screen Query with RANK() OVER:
            SELECT
                origin_id,
                destination_id,
                origin_id || ' -> ' || destination_id AS route,
                bookings,
                total_revenue,
                RANK() OVER (ORDER BY total_revenue DESC) AS revenue_rank
            FROM route_revenue_mv
            ORDER BY revenue_rank ASC;
            ```

            **2. Refreshing Materialized View via PL/SQL**
            ```sql
            BEGIN
                DBMS_MVIEW.REFRESH('ROUTE_REVENUE_MV');
            END;
            ```

            **3. Daily Revenue with LAG() and Cumulative Running Total (SUM() OVER)**
            ```sql
            SELECT
                booking_day,
                daily_revenue,
                LAG(daily_revenue) OVER (ORDER BY booking_day) AS prev_day_revenue,
                ROUND(daily_revenue - LAG(daily_revenue) OVER (ORDER BY booking_day), 2) AS daily_change,
                SUM(daily_revenue) OVER (
                    ORDER BY booking_day 
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS running_revenue
            FROM daily_revenue_v
            ORDER BY booking_day ASC;
            ```
            """
        )


# =============================================================
# PAGE 2: SEARCH AND BOOK
# =============================================================
elif page == "✈️ Search and Book":
    st.markdown('<div class="main-header">Search Flights & Reserve Seats</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Explore schedules across time zones and create instant bookings with automated payments</div>', unsafe_allow_html=True)

    df_airports = get_airports()
    airport_options = ["All"] + [f"{row['airport_id']} - {row['city']} ({row['name']})" for _, row in df_airports.iterrows()]
    airport_code_map = {"All": "All"}
    for _, row in df_airports.iterrows():
        label = f"{row['airport_id']} - {row['city']} ({row['name']})"
        airport_code_map[label] = row["airport_id"]

    # Filter controls
    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        origin_choice = st.selectbox("Origin Airport", airport_options, index=0)
        selected_origin = airport_code_map[origin_choice]
    with f_col2:
        dest_choice = st.selectbox("Destination Airport", airport_options, index=0)
        selected_dest = airport_code_map[dest_choice]
    with f_col3:
        target_timezone = st.selectbox(
            "Display Timezone (AT TIME ZONE)",
            ["Asia/Kolkata", "Asia/Dubai", "Europe/London", "America/New_York"],
            index=0,
        )

    # Matching Flights
    try:
        df_matched_flights = search_flights(selected_origin, selected_dest, target_timezone)
        st.markdown(f"#### Matching Flights ({len(df_matched_flights)} found)")

        if not df_matched_flights.empty:
            df_flights_view = df_matched_flights.copy()
            df_flights_view["formatted_fare"] = df_flights_view["fare"].apply(format_inr)
            df_flights_view["route"] = df_flights_view["origin_id"] + " (" + df_flights_view["origin_city"] + ") -> " + \
                                      df_flights_view["destination_id"] + " (" + df_flights_view["destination_city"] + ")"
            
            st.dataframe(
                df_flights_view[[
                    "flight_id", "flight_no", "route", "local_departure", "local_arrival", "formatted_fare"
                ]].rename(columns={
                    "flight_id": "ID",
                    "flight_no": "Flight No",
                    "route": "Route",
                    "local_departure": f"Departure ({target_timezone})",
                    "local_arrival": f"Arrival ({target_timezone})",
                    "formatted_fare": "Fare",
                }),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.warning("No flights found matching the selected origin and destination.")
    except Exception as e:
        st.error(f"Flight search error: {e}")

    st.markdown("---")

    # Booking Form
    st.subheader("📝 New Booking & Payment Form")
    st.caption("Inserts into `Bookings` (with JSON metadata) and `Payments` inside ONE atomic database transaction")

    df_passengers = get_passengers_list()
    df_all_flights = get_all_flights_for_booking()

    if not df_passengers.empty and not df_all_flights.empty:
        passenger_dict = {f"#{row['passenger_id']}: {row['name']} ({row['email']})": row['passenger_id'] for _, row in df_passengers.iterrows()}
        flight_dict = {
            f"Flight {row['flight_no']} ({row['city_route']}) - {format_inr(row['fare'])}": (row['flight_id'], float(row['fare']))
            for _, row in df_all_flights.iterrows()
        }

        with st.form("flight_booking_form"):
            b_col1, b_col2 = st.columns(2)
            with b_col1:
                selected_passenger_label = st.selectbox("Select Passenger", list(passenger_dict.keys()))
                selected_special = st.selectbox(
                    "Special Request (saved as JSON in metadata)",
                    ["none", "extra legroom", "wheelchair", "pet carrier", "infant"],
                )
            with b_col2:
                selected_flight_label = st.selectbox("Select Flight", list(flight_dict.keys()))
                payment_method = st.selectbox("Payment Method", ["UPI", "CARD", "NETBANKING", "WALLET"])

            c_col1, c_col2 = st.columns(2)
            with c_col1:
                payment_currency = st.radio("Payment Currency", ["INR", "USD"], horizontal=True)
            with c_col2:
                # Dynamic fare calculation
                flight_id, flight_fare = flight_dict[selected_flight_label]
                if payment_currency == "USD":
                    payable_amount = round(flight_fare / 83.0, 2)
                    st.info(f"**Payable Amount:** ${payable_amount:,.2f} USD *(Converted from {format_inr(flight_fare)} at 83 INR/USD)*")
                else:
                    payable_amount = flight_fare
                    st.info(f"**Payable Amount:** {format_inr(payable_amount)} INR")

            submitted = st.form_submit_button("Confirm Booking & Pay", type="primary", use_container_width=True)

            if submitted:
                passenger_id = passenger_dict[selected_passenger_label]
                try:
                    booking_res = db.book_flight(
                        passenger_id=passenger_id,
                        flight_id=flight_id,
                        special_request=selected_special,
                        payment_method=payment_method,
                        currency=payment_currency,
                        fare_inr=flight_fare,
                    )
                    st.cache_data.clear()
                    st.success(
                        f"🎉 **Booking Confirmed Successfully!**\n\n"
                        f"- **Booking ID**: #{booking_res['booking_id']}\n"
                        f"- **Payment ID**: #{booking_res['payment_id']}\n"
                        f"- **Amount Paid**: {booking_res['currency']} {booking_res['amount']:,.2f}\n"
                        f"- **Status**: {booking_res['status']}\n"
                        f"- **Special Request**: `{selected_special}` (persisted in JSON metadata)"
                    )
                except Exception as e:
                    st.error(f"Transaction Failed: {e}")

    with st.expander("🔍 View SQL (Search & Booking Transaction)"):
        st.markdown(
            """
            **1. Flight Search with AT TIME ZONE Expression**
            ```sql
            SELECT
                f.flight_id,
                f.flight_no,
                f.origin_id,
                f.destination_id,
                a1.city AS origin_city,
                a2.city AS destination_city,
                f.fare,
                f.currency,
                TO_CHAR(f.departure_time AT TIME ZONE :target_tz, 'YYYY-MM-DD HH24:MI:SS') AS local_departure,
                TO_CHAR(f.arrival_time AT TIME ZONE :target_tz, 'YYYY-MM-DD HH24:MI:SS') AS local_arrival
            FROM Flights f
            JOIN Airports a1 ON f.origin_id = a1.airport_id
            JOIN Airports a2 ON f.destination_id = a2.airport_id
            WHERE (:orig IS NULL OR f.origin_id = :orig)
              AND (:dest IS NULL OR f.destination_id = :dest)
            ORDER BY f.departure_time ASC;
            ```

            **2. Atomic Transactional Insert (Bookings + Payments with JSON Metadata)**
            ```sql
            -- Step 1: Find next primary keys
            SELECT NVL(MAX(booking_id), 0) + 1 FROM Bookings;
            SELECT NVL(MAX(payment_id), 0) + 1 FROM Payments;

            -- Step 2: Insert Booking with JSON metadata
            INSERT INTO Bookings (
                booking_id, passenger_id, flight_id, booking_date, status, metadata
            ) VALUES (
                :next_booking_id, :passenger_id, :flight_id, TRUNC(SYSDATE), 'CONFIRMED', :metadata_json
            );

            -- Step 3: Insert Payment
            INSERT INTO Payments (
                payment_id, booking_id, amount, currency, payment_method, status, payment_date
            ) VALUES (
                :next_payment_id, :next_booking_id, :amount, :currency, :method, 'SUCCESS', TRUNC(SYSDATE)
            );

            -- Step 4: COMMIT (or ROLLBACK on any failure)
            COMMIT;
            ```
            """
        )


# =============================================================
# PAGE 3: BOOKINGS
# =============================================================
elif page == "📋 Bookings":
    st.markdown('<div class="main-header">Booking Management & Status Tracking</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Query the `booking_details_v` database view, filter reservations, and cancel bookings</div>', unsafe_allow_html=True)

    try:
        df_bookings = get_bookings_table()
    except Exception as e:
        st.error(f"Error fetching bookings: {e}")
        df_bookings = pd.DataFrame()

    if not df_bookings.empty:
        # Filter controls
        bf_col1, bf_col2, bf_col3 = st.columns([1, 1, 1.5])
        with bf_col1:
            status_options = ["All"] + sorted(list(df_bookings["status"].unique()))
            selected_status = st.selectbox("Filter by Status", status_options, index=0)
        with bf_col2:
            route_options = ["All"] + sorted(list(df_bookings["route"].unique()))
            selected_route = st.selectbox("Filter by Route", route_options, index=0)
        with bf_col3:
            df_bookings["booking_date_dt"] = pd.to_datetime(df_bookings["booking_date"])
            min_date = df_bookings["booking_date_dt"].min().date()
            max_date = df_bookings["booking_date_dt"].max().date()
            date_range = st.date_input("Booking Date Range", [min_date, max_date], min_value=min_date, max_value=max_date)

        # Apply filters
        df_filtered = df_bookings.copy()
        if selected_status != "All":
            df_filtered = df_filtered[df_filtered["status"] == selected_status]
        if selected_route != "All":
            df_filtered = df_filtered[df_filtered["route"] == selected_route]
        if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
            start_d, end_d = date_range
            df_filtered = df_filtered[
                (df_filtered["booking_date_dt"].dt.date >= start_d) &
                (df_filtered["booking_date_dt"].dt.date <= end_d)
            ]

        st.markdown(f"**Showing {len(df_filtered)} of {len(df_bookings)} bookings**")

        # Display table
        df_view = df_filtered.copy()
        df_view["formatted_fare"] = df_view["fare"].apply(format_inr)
        df_view["booking_date"] = pd.to_datetime(df_view["booking_date"]).dt.strftime("%Y-%m-%d")
        
        st.dataframe(
            df_view[[
                "booking_id", "passenger", "flight_no", "route", "formatted_fare", "status", "booking_date"
            ]].rename(columns={
                "booking_id": "Booking ID",
                "passenger": "Passenger Name",
                "flight_no": "Flight No",
                "route": "Route",
                "formatted_fare": "Fare",
                "status": "Status",
                "booking_date": "Date",
            }),
            use_container_width=True,
            hide_index=True,
            height=400,
        )

        st.markdown("---")

        # Cancellation Action Box
        st.subheader("🚫 Cancel a Booking")
        st.caption("Cancels a booking by updating status to `'CANCELLED'` and committing the change")

        confirmed_bookings = df_bookings[df_bookings["status"] == "CONFIRMED"]
        if not confirmed_bookings.empty:
            c_col1, c_col2 = st.columns([3, 1])
            with c_col1:
                cancel_choice = st.selectbox(
                    "Choose Confirmed Booking to Cancel",
                    [
                        f"Booking #{row['booking_id']} - {row['passenger']} ({row['flight_no']} {row['route']})"
                        for _, row in confirmed_bookings.iterrows()
                    ],
                )
                cancel_id = int(cancel_choice.split()[1].replace("#", ""))
            with c_col2:
                st.write("")
                st.write("")
                if st.button("Cancel Booking", type="primary", use_container_width=True):
                    try:
                        db.cancel_booking(cancel_id)
                        st.cache_data.clear()
                        st.success(f"Booking #{cancel_id} has been marked as CANCELLED.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to cancel booking: {e}")
        else:
            st.info("No active confirmed bookings available to cancel.")

    with st.expander("🔍 View SQL (Booking Management)"):
        st.markdown(
            """
            **1. View Definition: `BOOKING_DETAILS_V`**
            ```sql
            CREATE OR REPLACE VIEW booking_details_v AS
            SELECT 
                b.booking_id,
                p.name AS passenger,
                f.flight_no,
                f.origin_id,
                f.destination_id,
                f.fare,
                b.status,
                b.booking_date
            FROM Bookings b
            JOIN Passengers p ON b.passenger_id = p.passenger_id
            JOIN Flights f ON b.flight_id = f.flight_id;
            ```

            **2. Screen Query with Filters**
            ```sql
            SELECT
                booking_id, passenger, flight_no, origin_id, destination_id,
                origin_id || ' -> ' || destination_id AS route,
                fare, status, booking_date
            FROM booking_details_v
            WHERE (:status IS NULL OR status = :status)
              AND (:route IS NULL OR origin_id || ' -> ' || destination_id = :route)
              AND booking_date BETWEEN :start_date AND :end_date
            ORDER BY booking_id DESC;
            ```

            **3. Cancel Booking DML Statement**
            ```sql
            UPDATE Bookings
            SET status = 'CANCELLED'
            WHERE booking_id = :booking_id;

            COMMIT;
            ```
            """
        )


# =============================================================
# PAGE 4: PASSENGERS (JSON)
# =============================================================
elif page == "👤 Passengers (JSON)":
    st.markdown('<div class="main-header">Passenger Directory & Native JSON Querying</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Demonstrating Oracle 23ai `JSON_VALUE` extraction of meal, seat, and numeric baggage preferences</div>', unsafe_allow_html=True)

    try:
        df_passengers = get_passengers_with_json()
        df_meals = get_meal_stats()

        # Passenger Meal Chart
        m_col1, m_col2 = st.columns([1.2, 1])
        with m_col1:
            fig_meal = px.bar(
                df_meals,
                x="meal_preference",
                y="passenger_count",
                title="Passenger Count by Meal Preference",
                labels={"meal_preference": "Meal Choice", "passenger_count": "Number of Passengers"},
                color="meal_preference",
                text_auto=True,
                color_discrete_sequence=px.colors.qualitative.Safe,
            )
            fig_meal.update_layout(showlegend=False, height=350, margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig_meal, use_container_width=True)

        with m_col2:
            st.markdown("#### Preferences Breakdown")
            st.dataframe(
                df_meals.rename(columns={"meal_preference": "Meal Type", "passenger_count": "Passengers"}),
                use_container_width=True,
                hide_index=True,
            )
            # Seat summary
            seat_counts = df_passengers["seat"].value_counts().reset_index()
            seat_counts.columns = ["Seat Type", "Passengers"]
            st.caption("**Seat Selections**")
            st.dataframe(seat_counts, use_container_width=True, hide_index=True)

        st.markdown("---")

        # Passengers Table
        st.subheader("All Passengers Table")
        search_term = st.text_input("🔍 Search by Passenger Name, Email, or Phone", "")
        if search_term:
            df_passengers = df_passengers[
                df_passengers["name"].str.contains(search_term, case=False, na=False) |
                df_passengers["email"].str.contains(search_term, case=False, na=False) |
                df_passengers["phone"].str.contains(search_term, case=False, na=False)
            ]

        st.dataframe(
            df_passengers.rename(columns={
                "passenger_id": "Passenger ID",
                "name": "Full Name",
                "email": "Email",
                "phone": "Phone",
                "meal": "Meal Preference (JSON)",
                "seat": "Seat Preference (JSON)",
                "baggage": "Baggage Pieces (JSON NUMBER)",
            }),
            use_container_width=True,
            hide_index=True,
            height=450,
        )
    except Exception as e:
        st.error(f"Error loading passengers: {e}")

    with st.expander("🔍 View SQL (JSON Querying Features)"):
        st.markdown(
            """
            **1. Querying JSON Columns using `JSON_VALUE`**
            ```sql
            SELECT
                passenger_id,
                name,
                email,
                phone,
                JSON_VALUE(preferences, '$.meal') AS meal,
                JSON_VALUE(preferences, '$.seat') AS seat,
                JSON_VALUE(preferences, '$.baggage' RETURNING NUMBER) AS baggage
            FROM Passengers
            ORDER BY passenger_id ASC;
            ```

            **2. Grouping and Aggregating on JSON Properties**
            ```sql
            SELECT
                NVL(JSON_VALUE(preferences, '$.meal'), 'Not Specified') AS meal_preference,
                COUNT(*) AS passenger_count
            FROM Passengers
            GROUP BY JSON_VALUE(preferences, '$.meal')
            ORDER BY passenger_count DESC;
            ```
            """
        )


# =============================================================
# PAGE 5: ANALYTICS
# =============================================================
elif page == "📈 Analytics":
    st.markdown('<div class="main-header">Advanced Booking & Payment Analytics</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Deep-dive financial reports demonstrating `HAVING`, multi-currency conversion, and conditional `CASE` logic</div>', unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs([
        "💳 Payment Methods (HAVING)",
        "💱 Multi-Currency Analysis",
        "🏷️ Fare Classes (CASE)",
    ])

    # Tab 1: Payment Methods Breakdown (GROUP BY with HAVING)
    with tab1:
        st.subheader("Payment Methods Breakdown")
        st.caption("Group functions with `HAVING COUNT(*) > 10` filter")

        try:
            df_payments = get_payment_methods_analytics()
            if not df_payments.empty:
                c1, c2 = st.columns([1.3, 1])
                with c1:
                    fig_pm = px.bar(
                        df_payments,
                        x="payment_method",
                        y="total_revenue_inr",
                        color="payment_method",
                        title="Total Revenue by Payment Method (INR)",
                        labels={"total_revenue_inr": "Revenue (₹)", "payment_method": "Method"},
                        text_auto=".2s",
                        color_discrete_sequence=px.colors.qualitative.Prism,
                    )
                    fig_pm.update_layout(showlegend=False, height=380)
                    st.plotly_chart(fig_pm, use_container_width=True)

                with c2:
                    df_pm_view = df_payments.copy()
                    df_pm_view["total_revenue_inr"] = df_pm_view["total_revenue_inr"].apply(format_inr)
                    df_pm_view["avg_transaction_inr"] = df_pm_view["avg_transaction_inr"].apply(format_inr)
                    st.dataframe(
                        df_pm_view.rename(columns={
                            "payment_method": "Payment Method",
                            "total_transactions": "Transactions",
                            "total_revenue_inr": "Total Revenue",
                            "avg_transaction_inr": "Avg Transaction",
                        }),
                        use_container_width=True,
                        hide_index=True,
                    )
        except Exception as e:
            st.error(f"Error loading payment methods analytics: {e}")

        with st.expander("🔍 View SQL (HAVING Clause)"):
            st.markdown(
                """
                ```sql
                SELECT
                    payment_method,
                    COUNT(*) AS total_transactions,
                    ROUND(SUM(CASE WHEN currency = 'USD' THEN amount * 83 ELSE amount END), 2) AS total_revenue_inr,
                    ROUND(AVG(CASE WHEN currency = 'USD' THEN amount * 83 ELSE amount END), 2) AS avg_transaction_inr
                FROM Payments
                WHERE status = 'SUCCESS'
                GROUP BY payment_method
                HAVING COUNT(*) > 10
                ORDER BY total_revenue_inr DESC;
                ```
                """
            )

    # Tab 2: Multi-Currency Analysis
    with tab2:
        st.subheader("Multi-Currency Breakdown (INR vs USD)")
        st.caption("Handling transactions in multiple currencies with conversion rate of 83 INR per USD")

        try:
            df_currency = get_currency_analytics()
            if not df_currency.empty:
                col_curr1, col_curr2 = st.columns(2)
                for i, row in df_currency.iterrows():
                    curr = row["currency"]
                    orig_sum = row["original_amount_sum"]
                    inr_equiv = row["inr_equivalent_sum"]
                    target_col = col_curr1 if curr == "INR" else col_curr2
                    with target_col:
                        target_col.metric(
                            f"{curr} Transactions",
                            f"{row['payment_count']} payments",
                            f"Total: {format_inr(inr_equiv)}" if curr == "USD" else f"Total: {format_inr(orig_sum)}",
                        )

                col_chart1, col_chart2 = st.columns(2)
                with col_chart1:
                    fig_curr_count = px.pie(
                        df_currency,
                        names="currency",
                        values="payment_count",
                        title="Payment Volume by Currency",
                        hole=0.4,
                        color_discrete_sequence=["#3B82F6", "#F59E0B"],
                    )
                    fig_curr_count.update_layout(height=350)
                    st.plotly_chart(fig_curr_count, use_container_width=True)

                with col_chart2:
                    fig_curr_rev = px.pie(
                        df_currency,
                        names="currency",
                        values="inr_equivalent_sum",
                        title="Normalized Revenue Proportion (in INR terms)",
                        hole=0.4,
                        color_discrete_sequence=["#3B82F6", "#10B981"],
                    )
                    fig_curr_rev.update_layout(height=350)
                    st.plotly_chart(fig_curr_rev, use_container_width=True)

                df_curr_view = df_currency.copy()
                df_curr_view["inr_equivalent_sum"] = df_curr_view["inr_equivalent_sum"].apply(format_inr)
                df_curr_view["avg_inr_equivalent"] = df_curr_view["avg_inr_equivalent"].apply(format_inr)
                st.dataframe(
                    df_curr_view.rename(columns={
                        "currency": "Currency",
                        "payment_count": "Transactions",
                        "original_amount_sum": "Original Currency Total",
                        "inr_equivalent_sum": "Total (INR Normalized)",
                        "avg_inr_equivalent": "Avg Transaction (INR)",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )
        except Exception as e:
            st.error(f"Error loading currency analytics: {e}")

        with st.expander("🔍 View SQL (Multi-Currency Grouping)"):
            st.markdown(
                """
                ```sql
                SELECT
                    currency,
                    COUNT(*) AS payment_count,
                    ROUND(SUM(amount), 2) AS original_amount_sum,
                    ROUND(SUM(CASE WHEN currency = 'USD' THEN amount * 83 ELSE amount END), 2) AS inr_equivalent_sum,
                    ROUND(AVG(CASE WHEN currency = 'USD' THEN amount * 83 ELSE amount END), 2) AS avg_inr_equivalent
                FROM Payments
                WHERE status = 'SUCCESS'
                GROUP BY currency
                ORDER BY currency ASC;
                ```
                """
            )

    # Tab 3: Fare Class Breakdown using CASE
    with tab3:
        st.subheader("Fare Class Classification via Conditional CASE")
        st.caption("Classified into: Budget (< ₹5,000), Standard (₹5,000 - ₹25,000), and Premium (> ₹25,000)")

        try:
            df_fare_classes = get_fare_class_analytics()
            if not df_fare_classes.empty:
                c_fc1, c_fc2 = st.columns([1.2, 1])
                with c_fc1:
                    fig_fc = px.bar(
                        df_fare_classes,
                        x="fare_class",
                        y="booking_count",
                        color="fare_class",
                        title="Bookings by Fare Tier",
                        labels={"booking_count": "Number of Bookings", "fare_class": "Tier"},
                        text_auto=True,
                        color_discrete_sequence=["#10B981", "#3B82F6", "#8B5CF6"],
                    )
                    fig_fc.update_layout(showlegend=False, height=380)
                    st.plotly_chart(fig_fc, use_container_width=True)

                with c_fc2:
                    df_fc_view = df_fare_classes.copy()
                    df_fc_view["total_fare_revenue"] = df_fc_view["total_fare_revenue"].apply(format_inr)
                    st.dataframe(
                        df_fc_view.rename(columns={
                            "fare_class": "Fare Class",
                            "booking_count": "Confirmed Bookings",
                            "total_fare_revenue": "Total Revenue",
                        }),
                        use_container_width=True,
                        hide_index=True,
                    )
        except Exception as e:
            st.error(f"Error loading fare class analytics: {e}")

        with st.expander("🔍 View SQL (CASE Expression Breakdown)"):
            st.markdown(
                """
                ```sql
                SELECT
                    fare_class,
                    COUNT(*) AS booking_count,
                    ROUND(SUM(fare_inr), 2) AS total_fare_revenue
                FROM (
                    SELECT
                        b.booking_id,
                        f.fare AS fare_inr,
                        CASE
                            WHEN f.fare < 5000 THEN 'Budget (< ₹5,000)'
                            WHEN f.fare <= 25000 THEN 'Standard (₹5,000 - ₹25,000)'
                            ELSE 'Premium (> ₹25,000)'
                        END AS fare_class
                    FROM Bookings b
                    JOIN Flights f ON b.flight_id = f.flight_id
                    WHERE b.status = 'CONFIRMED'
                )
                GROUP BY fare_class
                ORDER BY total_fare_revenue DESC;
                ```
                """
            )

