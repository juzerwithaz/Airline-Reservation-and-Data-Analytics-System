# Airline Reservation and Booking Analytics System ✈️

A comprehensive, production-grade airline reservation and data analytics platform connected to an **Oracle Database 23ai Free** instance (`FREEPDB1`). Built with a dual-portal architecture featuring a high-performance **FastAPI REST API backend**, an Emirates/Qatar Airways-inspired passenger and admin portal, and an internal **Streamlit analytics dashboard**.

---

## 🏛️ System Architecture

```
                                  ┌───────────────────────────────┐
                                  │   Oracle Database 23ai Free   │
                                  │     (localhost:1521/FREEPDB1) │
                                  └───────────────┬───────────────┘
                                                  │
                                                  │ (python-oracledb Thin Mode)
                                                  │
                         ┌────────────────────────┴────────────────────────┐
                         │                                                 │
                         ▼                                                 ▼
        ┌──────────────────────────────────┐             ┌──────────────────────────────────┐
        │        FastAPI REST API          │             │     Streamlit Analytics App      │
        │           (server.py)            │             │        (streamlit_app.py)        │
        │        Port: 8000 (/docs)        │             │            Port: 8501            │
        └────────────────┬─────────────────┘             └──────────────────────────────────┘
                         │
                         ▼ (JSON / REST API)
        ┌──────────────────────────────────┐
        │  Modern Airline Web Interface    │
        │           (index.html)           │
        └──────────────────────────────────┘
```

---

## 🛠️ Tech Stack

- **Database**: Oracle Database 23ai Free (`localhost:1521/FREEPDB1`, user: `airline`)
- **Backend API Engine**: [FastAPI](https://fastapi.tiangolo.com/) with [Uvicorn](https://www.uvicorn.org/)
- **Database Driver**: [python-oracledb](https://oracle.github.io/python-oracledb/) in **Thin Mode** (pure Python, requires zero Oracle Client / Instant Client installation)
- **Security & Password Hashing**: [Argon2id](https://pypi.org/project/argon2-cffi/) & RFC 7519 HMAC-SHA256 JWT tokens
- **Data Analysis & Visualization**: [pandas](https://pandas.pydata.org/), [Plotly](https://plotly.com/), and [Streamlit](https://streamlit.io/)
- **Frontend**: Responsive Tailwind CSS, JavaScript, Plotly.js (`index.html`)

---

## 🚀 Quick Start & Setup

### 1. Prerequisites
- **Python 3.10+** (Tested on Python 3.14)
- **Oracle Database 23ai Free** running locally on port 1521 (`FREEPDB1`)
- Verify Oracle Windows Services are running:
  - `OracleOraDB23Home1TNSListener`
  - `OracleServiceFREE`

### 2. Configure Environment (`.env`)
Create a `.env` file in the project root:
```ini
ORACLE_USER=airline
ORACLE_PASSWORD=airline123
ORACLE_DSN=localhost:1521/FREEPDB1
JWT_SECRET_KEY=your-super-secure-jwt-secret-key-2026
```

### 3. Bootstrap Administrator Account
Run the secure local administrator bootstrap script:
```bash
python setup_admin.py
```
*(Prompts for username, full name, email, and password, hashing credentials with Argon2id before saving to `ADMIN_USERS`)*

### 4. Start the FastAPI Backend Server
```bash
uvicorn server:app --reload --host 127.0.0.1 --port 8000
```
- **API Base URL**: `http://127.0.0.1:8000`
- **Interactive Swagger Documentation**: `http://127.0.0.1:8000/docs`
- **ReDoc Documentation**: `http://127.0.0.1:8000/redoc`

### 5. Launch the Streamlit Analytical App (Optional)
```bash
streamlit run streamlit_app.py
```
Opens in your browser at `http://localhost:8501`.

---

## 🧪 Verification & Automated Testing

Run the automated integration test suites against your live Oracle database:

```bash
# 1. Verify Database Layer & Sequences (Milestone 1)
python test_db_milestone1.py

# 2. Verify FastAPI Endpoints, Auth & Transactions (Milestone 2)
python test_server_milestone2.py
```

Both suites execute end-to-end against Oracle and verify zero data loss across existing records.

---

## 📚 REST API Reference

### System & Health
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Verifies Oracle database connectivity and returns server banner |
| `GET` | `/docs` | Interactive OpenAPI Swagger UI documentation |

### Passenger Authentication
| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/auth/passenger/register` | None | Register new passenger account (`PASSENGER_SEQ.NEXTVAL`, Argon2id hash) |
| `POST` | `/api/auth/passenger/login` | None | Passenger login; returns 2-hour JWT Bearer token |
| `POST` | `/api/auth/passenger/claim` | None | Claim existing seeded passenger account using admin activation code |
| `GET` | `/api/passenger/me` | Bearer (Passenger) | Retrieve profile of authenticated passenger |

### Administrator Authentication & Operations
| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/auth/admin/login` | None | Administrator login via `ADMIN_USERS`; returns role-based JWT token |
| `GET` | `/api/admin/me` | Bearer (Admin) | Retrieve profile and role of authenticated administrator |
| `POST` | `/api/admin/passengers/issue-activation` | Bearer (Admin) | Generate and issue single-use activation code for existing passenger |

### Flights & Passenger Bookings
| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/flights` | None | Search flights with Oracle `AT TIME ZONE` projection (`origin`, `destination`, `timezone`) |
| `GET` | `/api/flights/{id}` | None | Get detailed flight schedule and fare |
| `POST` | `/api/bookings` | Bearer (Passenger) | Atomic booking + payment creation using `BOOKING_SEQ` & `PAYMENT_SEQ` |
| `GET` | `/api/bookings/my` | Bearer (Passenger) | View personal booking history with real-time status and payment records |
| `POST` | `/api/bookings/{id}/cancel` | Bearer (Passenger) | Cancel eligible booking (enforces passenger ownership) |

### Administrator Record Management (CRUD)
| Method | Endpoint | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/admin/airports` | Bearer (Admin) | List all airports |
| `POST` | `/api/admin/airports` | Bearer (Admin) | Add a new airport |
| `PUT` | `/api/admin/airports/{code}` | Bearer (Admin) | Update airport details |
| `DELETE` | `/api/admin/airports/{code}` | Bearer (Admin) | Delete airport (safely validates foreign key usage in flights first) |
| `GET` | `/api/admin/flights` | Bearer (Admin) | List all flights |
| `POST` | `/api/admin/flights` | Bearer (Admin) | Schedule a new flight |
| `PATCH` | `/api/admin/flights/{id}/fare` | Bearer (Admin) | Update fare for an existing flight |
| `GET` | `/api/admin/passengers` | Bearer (Admin) | Search passengers and view booking history |
| `GET` | `/api/admin/bookings` | Bearer (Admin) | Filter and view all bookings across the fleet |
| `GET` | `/api/admin/payments` | Bearer (Admin) | Audit-only payment transaction viewing (immutable records) |

### Advanced SQL Analytics & View SQL Transparency
| Method | Endpoint | Auth | Advanced SQL Demonstrated |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/admin/analytics/kpis` | Bearer (Admin) | Fleet KPIs calculated in single-pass aggregation |
| `GET` | `/api/admin/analytics/route-ranking` | Bearer (Admin) | Route income rankings via `RANK() OVER (ORDER BY revenue DESC)` |
| `GET` | `/api/admin/analytics/day-over-day` | Bearer (Admin) | Revenue growth trends via `LAG()` |
| `GET` | `/api/admin/analytics/cumulative-revenue` | Bearer (Admin) | Running revenue totals via `SUM() OVER (ROWS UNBOUNDED PRECEDING)` |
| `GET` | `/api/admin/analytics/meal-preferences` | Bearer (Admin) | Native JSON document extraction via `JSON_VALUE(preferences, '$.meal')` |
| `GET` | `/api/admin/analytics/route-revenue-mv` | Bearer (Admin) | Queries pre-aggregated `ROUTE_REVENUE_MV` materialized view |
| `POST` | `/api/admin/analytics/refresh-mv` | Bearer (Admin) | On-demand materialized view refresh via `DBMS_MVIEW.REFRESH` |
| `GET` | `/api/admin/analytics/sql-explanations` | None | Returns transparent query definitions for UI **"🔍 View SQL"** drawers |

---

## 🔒 Security & Data Integrity Features

1. **Argon2id Password Security**:
   - Resistant to GPU/ASIC brute-force attacks via memory-hard computational complexity.
   - Zero hardcoded passwords; passwords are never logged or exposed in API responses.
2. **Oracle Sequence ID Generation**:
   - `BOOKING_SEQ.NEXTVAL`, `PASSENGER_SEQ.NEXTVAL`, and `PAYMENT_SEQ.NEXTVAL` guarantee collision-free concurrent inserts.
3. **Account Claiming Workflow**:
   - Seeded passengers (from original seed scripts) possess no default passwords.
   - Administrators generate a high-entropy 32-byte activation token. Oracle stores only the SHA-256 digest (`activation_token_hash`) with a time expiration.
4. **ACID Transaction Control**:
   - Booking operations insert into `Bookings` and `Payments` under a single Oracle transaction (`conn.autocommit = False`), committing only when both succeed.
