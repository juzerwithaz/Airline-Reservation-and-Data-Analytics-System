# AZ Airlines — Deployment Architecture & Production Guide

This guide details the deployment architecture for the **AZ Airlines Reservation and Booking Analytics System**, specifically addressing cloud hosting constraints, network connectivity between Vercel and Oracle Database, environment configuration, and zero-cost options.

---

## 1. Architectural Challenge & Analysis

### The Core Problem
- The frontend is hosted statically (e.g. on Vercel at `https://airline101.vercel.app/`).
- The backend is a FastAPI REST API (`server.py`).
- The database is **Oracle Database 23ai Free** running locally on `localhost:1521/FREEPDB1`.
- **Browsers and cloud-hosted services on Vercel cannot reach `http://127.0.0.1` or `localhost:1521` on your local physical computer**, because `localhost` resolves to the visitor's local machine, not your host computer.
- Calling an unencrypted `http://` backend from an `https://` Vercel site triggers browser **Mixed Content Blocking**.

---

## 2. Practical Deployment Options

### Option A: Zero-Cost Hybrid Architecture (Recommended for Academic Demos)
Keep your local Oracle 23ai Free database running on your machine, host the static frontend on Vercel, and expose your local FastAPI backend via a secure HTTPS tunnel.

```
┌───────────────────────────┐      HTTPS (Fetch)     ┌──────────────────────────────────┐
│ Vercel Frontend           │ ─────────────────────> │ Cloudflare Tunnel / ngrok        │
│ (https://airline101.      │                        │ (https://api-tunnel.yourdomain)  │
│  vercel.app)              │                        └────────────────┬─────────────────┘
└───────────────────────────┘                                         │ Localhost Proxy
                                                                      ▼
┌───────────────────────────┐      Thin Driver (1521)┌──────────────────────────────────┐
│ Oracle Database 23ai Free │ <───────────────────── │ FastAPI Backend (server.py)      │
│ (FREEPDB1)                │                        │ http://127.0.0.1:8000            │
└───────────────────────────┘                        └──────────────────────────────────┘
```

#### Step-by-Step Execution:
1. **Start FastAPI Locally**:
   ```powershell
   uvicorn server:app --reload --port 8000
   ```
2. **Start a Free Cloudflare Tunnel or ngrok**:
   - Using Cloudflare Tunnel (No account required for quick tunnels):
     ```bash
     cloudflared tunnel --url http://127.0.0.1:8000
     ```
     *(Cloudflare gives you an instant HTTPS URL like `https://random-subdomain.trycloudflare.com`)*
   - Or using ngrok:
     ```bash
     ngrok http 8000
     ```
3. **Configure the Vercel Frontend**:
   - Open your deployed site: `https://airline101.vercel.app/`
   - Click the **⚙️ API Config** button in the footer.
   - Paste your tunnel HTTPS URL (`https://...trycloudflare.com`) and click **Save & Connect**.
   - The frontend will now communicate directly with your local FastAPI backend and Oracle database over SSL!

---

### Option B: Cloud-Hosted Architecture (Autonomous DB + Cloud Backend)
For a 100% cloud deployment with zero dependence on a local laptop:

1. **Database Tier**:
   - Deploy an **Oracle Cloud Infrastructure (OCI) Always Free Autonomous Transaction Processing (ATP)** instance.
   - OCI Always Free provides 2 Autonomous Databases with 20 GB storage each for free forever.
   - Download the client credentials wallet (`Wallet_FREEPDB1.zip`).
2. **Backend Tier**:
   - Host FastAPI on **Render** (Free tier Web Service) or **Railway** or **OCI Compute VM**.
   - Set environment variables in Render:
     - `ORACLE_USER=airline`
     - `ORACLE_PASSWORD=YourPassword`
     - `ORACLE_DSN=tcps://adb.region.oraclecloud.com:1522/xxxx_high.adb.oraclecloud.com`
     - `JWT_SECRET_KEY=YourProductionSecretKey`
     - `CORS_ORIGINS=https://airline101.vercel.app`
3. **Frontend Tier**:
   - Deploy `index.html` to Vercel.
   - Set the default `API_BASE` to `https://your-api.onrender.com`.

---

## 3. Environment Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Description | Example |
| :--- | :--- | :--- |
| `ORACLE_USER` | Oracle schema username | `airline` |
| `ORACLE_PASSWORD` | Oracle schema password | `airline123` |
| `ORACLE_DSN` | Oracle Host / Service Name | `localhost:1521/FREEPDB1` |
| `JWT_SECRET_KEY` | HMAC-SHA256 signature key | Random 32+ character string |
| `CORS_ORIGINS` | Permitted frontend origins | `https://airline101.vercel.app,*` |
| `PORT` | API server port | `8000` |

---

## 4. Security & Compliance Checklist

- [x] **No Secrets Committed**: `.env` is listed in `.gitignore` and `.vercelignore`.
- [x] **Password Protection**: Passwords stored as Argon2id hashes with unique salts.
- [x] **JWT Expiration**: Access tokens expire after 2 hours and use cryptographic HMAC-SHA256 validation.
- [x] **Role Isolation**: RBAC enforces strict separation: passenger tokens rejected from staff endpoints (HTTP 403), unauthorized requests rejected (HTTP 401).
- [x] **SQL Injection Defense**: 100% of queries use parameterized bind variables (`:var`).
- [x] **Immutable Financial Ledger**: Payment records cannot be modified or deleted via API.
