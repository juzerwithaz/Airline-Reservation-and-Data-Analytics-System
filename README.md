# Airline Reservation and Booking Analytics System ✈️

A modern, responsive Streamlit web application front-end connected to an Oracle Database 23ai backend, engineered for comprehensive airline operations, passenger preference analysis, and revenue analytics.

---

## 🛠️ Tech Stack

- **Frontend & App Framework**: [Streamlit](https://streamlit.io/)
- **Database Driver**: [python-oracledb](https://oracle.github.io/python-oracledb/) in **Thin Mode** (pure Python, requires zero Oracle Client / Instant Client installation)
- **Data Manipulation & Analysis**: [pandas](https://pandas.pydata.org/)
- **Data Visualization**: [Plotly](https://plotly.com/python/) & native Streamlit chart components
- **Configuration & Security**: [python-dotenv](https://github.com/theskumar/python-dotenv) for `.env` credentials management

---

## 🚀 Quick Start & Setup

### 1. Prerequisites
- **Python 3.10+** (Tested on Python 3.14)
- **Oracle Database 23ai / 21c / 19c** (e.g., Oracle Database 23ai Free `FREEPDB1`)
- Ensure the Oracle Windows Services are running:
  - `OracleOraDB23Home1TNSListener`
  - `OracleServiceFREE`

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Database Credentials
Create a `.env` file in the project root directory (or copy from `.env.example`):
```ini
ORACLE_USER=airline
ORACLE_PASSWORD=airline123
ORACLE_DSN=localhost:1521/FREEPDB1
```

> **Security Note**: `.env` is listed in `.gitignore` and must never be committed to version control.

### 4. Run the Streamlit Application (Local)
```bash
streamlit run streamlit_app.py
```
The application will launch automatically in your web browser at `http://localhost:8501`.

### 5. Deploy to Vercel (1-Click Cloud Hosting)
1. Go to [vercel.com](https://vercel.com) and click **"Add New Project"**.
2. Select your repository: `juzerwithaz/Airline-Reservation-and-Data-Analytics-System`.
3. Keep default settings (Root directory `./`, Framework preset `Other/Static`).
4. Click **Deploy**!
Your full responsive application will be live in ~10 seconds with zero configuration required.

---

## 📁 Project Structure

```
oracle_airline_website/
├── index.html            # Vercel-ready responsive single-page web app (Tailwind + Plotly)
├── streamlit_app.py      # Streamlit web application for local development
├── db.py                 # Database connection helper (Thin-mode Oracle 23ai driver)
├── requirements.txt      # Python dependencies
├── .env                  # Environment file with database credentials (gitignored)
├── .env.example          # Sample environment configuration template
├── .gitignore            # Git ignore rules for virtualenv, .env, and caches
└── README.md             # Project documentation and architectural explanation
```

```
oracle_airline_website/
├── .env                  # Environment file with database credentials (gitignored)
├── .env.example          # Sample environment configuration template
├── .gitignore            # Git ignore rules for virtualenv, .env, and caches
├── requirements.txt      # Python dependencies
├── db.py                 # Database connection helper, thin-mode driver, and transactional DML functions
├── app.py                # Main Streamlit web application with sidebar navigation and interactive UI
└── README.md             # Project documentation and architectural explanation
```

---

## 📊 Application Screens & Key SQL Features Demonstrated

Every page includes an interactive **"🔍 View SQL"** drawer specifically included for academic presentation and interview defense:

### 1. 📊 Dashboard
- **Real-Time KPIs**: Total confirmed bookings, total revenue in INR, cancelled bookings, and active flight routes.
- **Route Revenue Rankings**: Queries `route_revenue_mv` using `RANK() OVER (ORDER BY total_revenue DESC)` to rank flight paths.
- **Materialized View On-Demand Refresh**: Interactive button that executes `BEGIN DBMS_MVIEW.REFRESH('ROUTE_REVENUE_MV'); END;` and invalidates the Streamlit query cache.
- **Daily Revenue & Cumulative Growth**: Queries `daily_revenue_v` leveraging `LAG()` for day-over-day variance and `SUM() OVER (ORDER BY ... ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` for cumulative revenue.

### 2. ✈️ Search and Book
- **Dynamic Timezone Conversion**: Searches flights between chosen airports and uses `AT TIME ZONE` (`Asia/Kolkata`, `Asia/Dubai`, `Europe/London`, `America/New_York`) to show local departure and arrival times.
- **ACID Transactional Booking & Payment**:
  - Automatically computes `booking_id = MAX(booking_id) + 1` and `payment_id = MAX(payment_id) + 1`.
  - Converts currency at **83 INR per USD** when USD is chosen.
  - Persists passenger special requests in the `metadata` JSON column (`{"special": "wheelchair"}`).
  - Commits both `Bookings` and `Payments` atomically in a single transaction, or rolls back completely upon error.

### 3. 📋 Bookings
- **View Integration**: Queries `booking_details_v` with multi-criteria filtering by reservation status, flight route, and date range.
- **Booking Cancellation**: Updates status to `CANCELLED` and commits, dynamically refreshing cached records.

### 4. 👤 Passengers (JSON)
- **Native JSON Querying**: Queries semi-structured attributes directly from relational table `Passengers` using:
  - `JSON_VALUE(preferences, '$.meal')`
  - `JSON_VALUE(preferences, '$.seat')`
  - `JSON_VALUE(preferences, '$.baggage' RETURNING NUMBER)`
- **Aggregation by JSON**: Groups passengers by meal preference to render visualization charts.

### 5. 📈 Analytics
- **Payment Method Analysis**: Uses aggregate functions with `HAVING COUNT(*) > 10` to analyze payment provider adoption.
- **Multi-Currency Normalization**: Visualizes distribution of INR vs USD transactions and normalizes revenues to INR.
- **Fare Tier Segmentation**: Employs SQL `CASE` expressions to segment flights into *Budget (< ₹5,000)*, *Standard (₹5,000 - ₹25,000)*, and *Premium (> ₹25,000)*.

---

## 🔒 Robustness & Caching Architecture
- **In-Memory Caching**: Read-only queries use `@st.cache_data(ttl=30)` for high-performance responsiveness without overloading the database.
- **Cache Invalidation**: Any mutation (booking confirmation, booking cancellation, or materialized view refresh) immediately calls `st.cache_data.clear()` to guarantee data consistency.
- **Resilience**: Database exceptions are trapped and surfaced through user-friendly Streamlit banners (`st.error`, `st.warning`) without crashing the application.

