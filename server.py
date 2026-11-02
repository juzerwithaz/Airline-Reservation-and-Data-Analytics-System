"""
server.py - FastAPI Backend Engine for Airline Reservation & Analytics System
=============================================================================
Provides REST API endpoints for:
- Passenger authentication (Register, Login, Claim Account)
- Administrator authentication & role-based authorization
- Flight search with Oracle AT TIME ZONE conversion
- Transactional booking and payment creation with sequences
- Passenger booking history and cancellation
- Admin record management (Airports, Flights, Passengers, Bookings, Payments)
- Advanced SQL analytics and on-demand Materialized View refresh
"""

import os
import time
import json
import hmac
import hashlib
import base64
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, status, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
from dotenv import load_dotenv

import db

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("airline_server")

load_dotenv()

# JWT configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "oracle-airline-super-secure-jwt-secret-key-2026")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_SECONDS = 7200  # 2 hours

app = FastAPI(
    title="Airline Reservation and Booking Analytics API",
    description="High-performance REST API connected directly to Oracle Database 23ai Free.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Configuration (Configurable via CORS_ORIGINS in .env for production deployment)
raw_cors = os.getenv("CORS_ORIGINS", "*")
allowed_origins = [o.strip() for o in raw_cors.split(",") if o.strip()] if raw_cors != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer(auto_error=False)


# ====================================================================
# JWT TOKEN HELPERS (RFC 7519 HMAC-SHA256)
# ====================================================================

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (4 - len(data) % 4) if len(data) % 4 != 0 else ""
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(payload: Dict[str, Any], expires_in: int = ACCESS_TOKEN_EXPIRE_SECONDS) -> str:
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    now = int(time.time())
    token_data = payload.copy()
    token_data["iat"] = now
    token_data["exp"] = now + expires_in

    header_b64 = _b64url_encode(json.dumps(header).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(token_data).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    signature = hmac.new(JWT_SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_access_token(token: str) -> Dict[str, Any]:
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token structure",
            headers={"WWW-Authenticate": "Bearer"},
        )

    signing_input = f"{parts[0]}.{parts[1]}".encode("utf-8")
    expected_sig = _b64url_encode(
        hmac.new(JWT_SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    )

    if not hmac.compare_digest(parts[2], expected_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    exp = payload.get("exp")
    if exp and time.time() > exp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


# ====================================================================
# AUTHENTICATION DEPENDENCIES & ROLE GUARDS
# ====================================================================

async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is missing. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_access_token(credentials.credentials)


async def require_passenger(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if current_user.get("role") != "PASSENGER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted: Passenger account required.",
        )
    return current_user


async def require_admin(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    role = current_user.get("role")
    if role not in ["SUPER_ADMIN", "FLIGHT_OPS", "SUPPORT"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted: Administrator privileges required.",
        )
    return current_user


# ====================================================================
# PYDANTIC REQUEST & RESPONSE SCHEMAS
# ====================================================================

class PassengerRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., max_length=100)
    phone: str = Field(..., min_length=5, max_length=15)
    password: str = Field(..., min_length=8)
    preferences: Optional[Dict[str, Any]] = None


class LoginRequest(BaseModel):
    username_or_email: str
    password: str


class ClaimAccountRequest(BaseModel):
    passenger_id: int
    activation_token: str
    new_password: str = Field(..., min_length=8)


class BookingCreateRequest(BaseModel):
    flight_id: int
    special_request: str = "Standard"
    payment_method: str = "CARD"
    currency: str = "INR"


class AirportCreateRequest(BaseModel):
    airport_id: str = Field(..., min_length=3, max_length=5, description="Airport code (e.g. DEL)")
    name: str = Field(..., min_length=3, max_length=100)
    city: str = Field(..., min_length=2, max_length=50)
    country: str = Field(..., min_length=2, max_length=50)
    timezone: str = Field(default="Asia/Kolkata", max_length=50)


class AirportUpdateRequest(BaseModel):
    name: str
    city: str
    country: str
    timezone: str


class FlightCreateRequest(BaseModel):
    flight_no: str = Field(..., min_length=3, max_length=10)
    origin_id: str = Field(..., min_length=3, max_length=5)
    destination_id: str = Field(..., min_length=3, max_length=5)
    departure_time: str = Field(..., description="Format: YYYY-MM-DD HH24:MI:SS TZR")
    arrival_time: str = Field(..., description="Format: YYYY-MM-DD HH24:MI:SS TZR")
    fare: float = Field(..., gt=0)
    currency: str = "INR"


class FlightUpdateFareRequest(BaseModel):
    fare: float = Field(..., gt=0)


class IssueTokenRequest(BaseModel):
    passenger_id: int
    expiry_days: int = 7


# ====================================================================
# 1. SYSTEM & HEALTH ENDPOINTS
# ====================================================================

@app.get("/health", tags=["System"])
def health_check():
    """
    Verify Oracle database connectivity and return instance version.
    """
    try:
        db_status = db.test_connection()
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "database": db_status,
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
        }


# ====================================================================
# 2. PASSENGER AUTHENTICATION
# ====================================================================

@app.post("/api/auth/passenger/register", tags=["Passenger Auth"])
def register_passenger_endpoint(req: PassengerRegisterRequest):
    """
    Register a new passenger:
    - Verifies email uniqueness in Passengers.
    - Generates next passenger ID from PASSENGER_SEQ.
    - Hashes password with Argon2id.
    - Inserts into Passengers and PASSENGER_AUTH with status 'ACTIVE'.
    - Returns JWT access token.
    """
    try:
        res = db.register_passenger(
            name=req.name,
            email=req.email,
            phone=req.phone,
            password=req.password,
            preferences=req.preferences,
        )
        token_payload = {
            "sub": str(res["passenger_id"]),
            "role": "PASSENGER",
            "email": res["email"],
            "name": res["name"],
        }
        token = create_access_token(token_payload)
        logger.info(f"New passenger registered: ID {res['passenger_id']} ({res['email']})")
        return {
            "message": "Registration successful",
            "access_token": token,
            "token_type": "bearer",
            "user": res,
        }
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error(f"Passenger registration error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/auth/passenger/login", tags=["Passenger Auth"])
def login_passenger_endpoint(req: LoginRequest):
    """
    Passenger login using email and password:
    - Verifies Argon2id password hash.
    - Checks account status (must be 'ACTIVE').
    - Returns JWT access token.
    """
    passenger = db.get_passenger_by_email(req.username_or_email)
    if not passenger:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    auth_status = passenger.get("auth_status")
    if auth_status == "NO_ACCOUNT" or not passenger.get("password_hash"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has not been activated yet. Please use your activation code to claim your account.",
        )

    if auth_status == "PENDING_ACTIVATION":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account pending activation. Please claim your account with your activation code.",
        )

    if auth_status == "SUSPENDED":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended. Please contact airline customer operations.",
        )

    if not db.verify_password(passenger["password_hash"], req.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    db.update_passenger_last_login(passenger["passenger_id"])
    token_payload = {
        "sub": str(passenger["passenger_id"]),
        "role": "PASSENGER",
        "email": passenger["email"],
        "name": passenger["name"],
    }
    token = create_access_token(token_payload)
    logger.info(f"Passenger logged in: ID {passenger['passenger_id']} ({passenger['email']})")
    return {
        "message": "Login successful",
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "passenger_id": passenger["passenger_id"],
            "name": passenger["name"],
            "email": passenger["email"],
            "phone": passenger["phone"],
            "preferences": passenger["preferences"],
        },
    }


@app.post("/api/auth/passenger/claim", tags=["Passenger Auth"])
def claim_passenger_endpoint(req: ClaimAccountRequest):
    """
    Activate an existing seeded passenger account using an admin-issued single-use activation code:
    - Validates SHA-256 token digest and expiry in PASSENGER_AUTH.
    - Sets verified password hash.
    - Transitions status to 'ACTIVE' and clears the token.
    - Returns JWT access token.
    """
    try:
        success = db.claim_passenger_account(
            passenger_id=req.passenger_id,
            raw_token=req.activation_token,
            new_password=req.new_password,
        )
        if not success:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Activation failed.")

        passenger = db.get_passenger_by_id(req.passenger_id)
        token_payload = {
            "sub": str(passenger["passenger_id"]),
            "role": "PASSENGER",
            "email": passenger["email"],
            "name": passenger["name"],
        }
        token = create_access_token(token_payload)
        logger.info(f"Passenger account claimed: ID {req.passenger_id}")
        return {
            "message": "Account activated successfully!",
            "access_token": token,
            "token_type": "bearer",
            "user": passenger,
        }
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error(f"Claim account error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/passenger/me", tags=["Passenger Auth"])
def get_current_passenger_profile(user: Dict[str, Any] = Depends(require_passenger)):
    """
    Retrieve authenticated passenger profile.
    """
    passenger_id = int(user["sub"])
    profile = db.get_passenger_by_id(passenger_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passenger not found.")
    return profile


# ====================================================================
# 3. ADMINISTRATOR AUTHENTICATION
# ====================================================================

@app.post("/api/auth/admin/login", tags=["Admin Auth"])
def login_admin_endpoint(req: LoginRequest):
    """
    Administrator login:
    - Queries ADMIN_USERS by username or email.
    - Verifies Argon2id password hash.
    - Checks active status.
    - Returns role-based JWT token.
    """
    admin = db.get_admin_by_username(req.username_or_email)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator credentials.",
        )

    if admin.get("status") != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator account is suspended.",
        )

    if not db.verify_password(admin["password_hash"], req.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator credentials.",
        )

    db.update_admin_last_login(admin["admin_id"])
    token_payload = {
        "sub": str(admin["admin_id"]),
        "role": admin["role"],
        "username": admin["username"],
        "email": admin["email"],
        "name": admin["full_name"],
    }
    token = create_access_token(token_payload)
    logger.info(f"Administrator logged in: {admin['username']} ({admin['role']})")
    return {
        "message": "Admin authentication successful",
        "access_token": token,
        "token_type": "bearer",
        "admin": {
            "admin_id": admin["admin_id"],
            "username": admin["username"],
            "email": admin["email"],
            "full_name": admin["full_name"],
            "role": admin["role"],
        },
    }


@app.get("/api/admin/me", tags=["Admin Auth"])
def get_current_admin_profile(user: Dict[str, Any] = Depends(require_admin)):
    """
    Retrieve authenticated administrator profile.
    """
    return user


@app.post("/api/admin/passengers/issue-activation", tags=["Admin Operations"])
def issue_passenger_activation_endpoint(
    req: IssueTokenRequest,
    admin: Dict[str, Any] = Depends(require_admin),
):
    """
    Administrator endpoint: Generate and issue a single-use activation code for an existing passenger.
    """
    try:
        raw_token = db.issue_passenger_activation_token(
            passenger_id=req.passenger_id,
            expiry_days=req.expiry_days,
        )
        logger.info(f"Admin {admin['username']} issued activation code for Passenger {req.passenger_id}")
        return {
            "passenger_id": req.passenger_id,
            "activation_code": raw_token,
            "expires_in_days": req.expiry_days,
            "message": "Activation code generated successfully. Share this securely with the passenger.",
        }
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error(f"Issue activation token error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ====================================================================
# 4. FLIGHT SEARCH & DETAILS (PUBLIC & PASSENGER)
# ====================================================================

@app.get("/api/flights", tags=["Flights"])
def search_flights_endpoint(
    origin: Optional[str] = Query(None, description="Origin Airport Code (e.g. BOM)"),
    destination: Optional[str] = Query(None, description="Destination Airport Code (e.g. DEL)"),
    date: Optional[str] = Query(None, description="Travel date in YYYY-MM-DD format"),
    timezone: str = Query("Asia/Kolkata", description="Target local timezone for AT TIME ZONE projection"),
):
    """
    Search available flights with accurate timezone conversion using Oracle's AT TIME ZONE.
    Validates that origin and destination cannot be identical.
    """
    if origin and destination and origin.strip().upper() == destination.strip().upper():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Origin and destination airports cannot be identical.",
        )

    if date:
        try:
            datetime.strptime(date.strip(), "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Expected YYYY-MM-DD.",
            )

    try:
        flights = db.search_flights(
            origin_airport_id=origin,
            destination_airport_id=destination,
            flight_date=date,
            target_timezone=timezone,
        )
        return {"count": len(flights), "timezone": timezone, "flights": flights}
    except Exception as e:
        logger.error(f"Flight search error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/flights/{flight_id}", tags=["Flights"])
def get_flight_details_endpoint(
    flight_id: int,
    timezone: str = Query("Asia/Kolkata"),
):
    """
    Retrieve full details for a specific flight.
    """
    flights = db.search_flights(target_timezone=timezone)
    for f in flights:
        if f["flight_id"] == flight_id:
            return f
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Flight {flight_id} not found.")


# ====================================================================
# 5. PASSENGER BOOKING OPERATIONS
# ====================================================================

@app.post("/api/bookings", tags=["Passenger Bookings"])
def create_booking_endpoint(
    req: BookingCreateRequest,
    user: Dict[str, Any] = Depends(require_passenger),
):
    """
    Create a new booking and payment record inside a single Oracle ACID transaction:
    1. Derives authenticated passenger ID from backend JWT session.
    2. Fetches flight fare and details from Flights table.
    3. Allocates unique IDs using BOOKING_SEQ.NEXTVAL and PAYMENT_SEQ.NEXTVAL.
    4. Inserts into Bookings and Payments atomically.
    5. Returns booking confirmation reference.
    """
    passenger_id = int(user["sub"])

    # Fetch flight to verify existence and fare
    flights = db.search_flights()
    target_flight = next((f for f in flights if f["flight_id"] == req.flight_id), None)
    if not target_flight:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Flight ID {req.flight_id} does not exist.",
        )

    try:
        booking_result = db.book_flight(
            passenger_id=passenger_id,
            flight_id=req.flight_id,
            special_request=req.special_request,
            payment_method=req.payment_method,
            currency=req.currency,
            fare_inr=float(target_flight["fare"]),
        )
        logger.info(f"Booking created: ID {booking_result['booking_id']} by Passenger {passenger_id}")
        return {
            "message": "Flight booked successfully!",
            "booking": booking_result,
            "flight": {
                "flight_no": target_flight["flight_no"],
                "route": f"{target_flight['origin_city']} -> {target_flight['destination_city']}",
                "departure": target_flight["departure_time_local"],
                "arrival": target_flight["arrival_time_local"],
            },
        }
    except Exception as e:
        logger.error(f"Booking creation error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/bookings/my", tags=["Passenger Bookings"])
def get_my_bookings_endpoint(user: Dict[str, Any] = Depends(require_passenger)):
    """
    Retrieve booking history and associated payment statuses for the authenticated passenger.
    """
    passenger_id = int(user["sub"])
    try:
        bookings = db.get_passenger_bookings_history(passenger_id)
        return {"passenger_id": passenger_id, "count": len(bookings), "bookings": bookings}
    except Exception as e:
        logger.error(f"Fetch booking history error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/bookings/{booking_id}/cancel", tags=["Passenger Bookings"])
def cancel_booking_endpoint(
    booking_id: int,
    user: Dict[str, Any] = Depends(require_passenger),
):
    """
    Cancel an eligible booking for the authenticated passenger.
    Guarantees that a passenger cannot cancel another user's booking.
    """
    passenger_id = int(user["sub"])
    try:
        db.cancel_passenger_booking(booking_id=booking_id, passenger_id=passenger_id)
        logger.info(f"Booking {booking_id} cancelled by Passenger {passenger_id}")
        return {"message": f"Booking {booking_id} cancelled successfully.", "booking_id": booking_id}
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error(f"Cancellation error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/bookings/{booking_id}", tags=["Passenger Bookings"])
def get_booking_details_endpoint(
    booking_id: int,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Retrieve full details for a specific booking and associated payment.
    Enforces authorization: passengers can only view their own bookings,
    while administrators can inspect any booking.
    """
    is_admin = user.get("role") in ["SUPER_ADMIN", "FLIGHT_OPS", "SUPPORT", "ADMIN"]
    passenger_id = None if is_admin else int(user["sub"])
    booking = db.get_booking_details(booking_id, passenger_id=passenger_id)
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Booking #{booking_id} not found or access denied.",
        )
    return booking


# ====================================================================
# 6. ADMINISTRATOR RECORD MANAGEMENT (CRUD)
# ====================================================================

# --- Airports CRUD ---

@app.get("/api/admin/airports", tags=["Admin CRUD"])
def get_all_airports(admin: Dict[str, Any] = Depends(require_admin)):
    return db.admin_get_airports()


@app.post("/api/admin/airports", tags=["Admin CRUD"])
def create_airport_endpoint(req: AirportCreateRequest, admin: Dict[str, Any] = Depends(require_admin)):
    try:
        res = db.admin_create_airport(
            airport_id=req.airport_id,
            name=req.name,
            city=req.city,
            country=req.country,
            timezone=req.timezone,
        )
        return {"message": f"Airport {req.airport_id} created successfully.", "airport": res}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.put("/api/admin/airports/{airport_id}", tags=["Admin CRUD"])
def update_airport_endpoint(
    airport_id: str,
    req: AirportUpdateRequest,
    admin: Dict[str, Any] = Depends(require_admin),
):
    try:
        db.admin_update_airport(
            airport_id=airport_id,
            name=req.name,
            city=req.city,
            country=req.country,
            timezone=req.timezone,
        )
        return {"message": f"Airport {airport_id} updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.delete("/api/admin/airports/{airport_id}", tags=["Admin CRUD"])
def delete_airport_endpoint(airport_id: str, admin: Dict[str, Any] = Depends(require_admin)):
    try:
        db.admin_delete_airport(airport_id=airport_id)
        return {"message": f"Airport {airport_id} deleted successfully."}
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# --- Flights CRUD ---

@app.get("/api/admin/flights", tags=["Admin CRUD"])
def get_all_flights(admin: Dict[str, Any] = Depends(require_admin)):
    return db.admin_get_flights()


@app.post("/api/admin/flights", tags=["Admin CRUD"])
def create_flight_endpoint(req: FlightCreateRequest, admin: Dict[str, Any] = Depends(require_admin)):
    if req.origin_id.strip().upper() == req.destination_id.strip().upper():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Origin and destination airports cannot be identical.",
        )
    try:
        res = db.admin_create_flight(
            flight_no=req.flight_no,
            origin_id=req.origin_id,
            destination_id=req.destination_id,
            departure_str=req.departure_time,
            arrival_str=req.arrival_time,
            fare=req.fare,
            currency=req.currency,
        )
        return {"message": f"Flight {req.flight_no} created successfully.", "flight": res}
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.patch("/api/admin/flights/{flight_id}/fare", tags=["Admin CRUD"])
def update_flight_fare_endpoint(
    flight_id: int,
    req: FlightUpdateFareRequest,
    admin: Dict[str, Any] = Depends(require_admin),
):
    try:
        db.admin_update_flight(flight_id=flight_id, fare=req.fare)
        return {"message": f"Flight {flight_id} fare updated to {req.fare}."}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.delete("/api/admin/flights/{flight_id}", tags=["Admin CRUD"])
def delete_flight_endpoint(flight_id: int, admin: Dict[str, Any] = Depends(require_admin)):
    """
    Delete a flight if no active confirmed bookings exist.
    """
    try:
        db.admin_delete_flight(flight_id)
        return {"message": f"Flight {flight_id} deleted successfully."}
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        logger.error(f"Delete flight error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# --- Passengers Management ---

@app.get("/api/admin/passengers", tags=["Admin CRUD"])
def get_passengers_endpoint(
    search: Optional[str] = Query(None),
    admin: Dict[str, Any] = Depends(require_admin),
):
    return db.admin_get_passengers(search=search)


@app.get("/api/admin/passengers/{passenger_id}", tags=["Admin CRUD"])
def get_single_passenger_endpoint(passenger_id: int, admin: Dict[str, Any] = Depends(require_admin)):
    """
    Retrieve passenger details along with their full booking history.
    """
    passenger = db.get_passenger_by_id(passenger_id)
    if not passenger:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Passenger #{passenger_id} not found.")
    bookings = db.get_passenger_bookings_history(passenger_id)
    return {
        "passenger": passenger,
        "total_bookings": len(bookings),
        "bookings": bookings,
    }


# --- Bookings & Payments Management ---

@app.get("/api/admin/bookings", tags=["Admin CRUD"])
def get_all_bookings_endpoint(
    status_filter: Optional[str] = Query(None, alias="status"),
    admin: Dict[str, Any] = Depends(require_admin),
):
    return db.admin_get_bookings(status=status_filter)


@app.get("/api/admin/payments", tags=["Admin CRUD"])
def get_all_payments_endpoint(
    status_filter: Optional[str] = Query(None, alias="status"),
    admin: Dict[str, Any] = Depends(require_admin),
):
    """
    Audit-only payment viewing for administrators.
    Payments are immutable financial transaction records.
    """
    return db.admin_get_payments(status=status_filter)


# ====================================================================
# 7. ADMINISTRATOR ANALYTICS & ADVANCED SQL DEMOS
# ====================================================================

@app.get("/api/admin/analytics/kpis", tags=["Admin Analytics"])
def get_kpis_endpoint(admin: Dict[str, Any] = Depends(require_admin)):
    """
    Return system-wide operational KPIs computed directly from Oracle aggregations.
    """
    return {
        "data": db.get_admin_kpis(),
        "sql": db.SQL_EXPLANATIONS["kpis"],
    }


@app.get("/api/admin/analytics/route-ranking", tags=["Admin Analytics"])
def get_route_ranking_endpoint(admin: Dict[str, Any] = Depends(require_admin)):
    """
    Return route ranking computed with Oracle analytic function RANK() OVER.
    """
    return {
        "data": db.get_route_ranking(),
        "sql": db.SQL_EXPLANATIONS["route_ranking"],
    }


@app.get("/api/admin/analytics/day-over-day", tags=["Admin Analytics"])
def get_day_over_day_endpoint(admin: Dict[str, Any] = Depends(require_admin)):
    """
    Return day-over-day revenue differences computed with Oracle LAG().
    """
    return {
        "data": db.get_day_over_day_revenue(),
        "sql": db.SQL_EXPLANATIONS["day_over_day"],
    }


@app.get("/api/admin/analytics/cumulative-revenue", tags=["Admin Analytics"])
def get_cumulative_revenue_endpoint(admin: Dict[str, Any] = Depends(require_admin)):
    """
    Return running total revenue computed with Oracle SUM() OVER.
    """
    return {
        "data": db.get_cumulative_revenue(),
        "sql": db.SQL_EXPLANATIONS["cumulative_revenue"],
    }


@app.get("/api/admin/analytics/meal-preferences", tags=["Admin Analytics"])
def get_meal_preferences_endpoint(admin: Dict[str, Any] = Depends(require_admin)):
    """
    Return meal choices extracted from JSON documents with Oracle JSON_VALUE.
    """
    return {
        "data": db.get_passenger_meal_preferences(),
        "sql": db.SQL_EXPLANATIONS["meal_preferences"],
    }


@app.get("/api/admin/analytics/route-revenue-mv", tags=["Admin Analytics"])
def get_route_revenue_mv_endpoint(admin: Dict[str, Any] = Depends(require_admin)):
    """
    Return pre-aggregated route performance from ROUTE_REVENUE_MV.
    """
    return {
        "data": db.get_route_revenue_mv_data(),
        "sql": db.SQL_EXPLANATIONS["route_revenue_mv"],
    }


@app.post("/api/admin/analytics/refresh-mv", tags=["Admin Analytics"])
def refresh_materialized_view_endpoint(admin: Dict[str, Any] = Depends(require_admin)):
    """
    Trigger on-demand DBMS_MVIEW.REFRESH('ROUTE_REVENUE_MV') in Oracle.
    """
    try:
        db.refresh_route_revenue_mv()
        logger.info(f"Admin {admin['username']} triggered ROUTE_REVENUE_MV refresh.")
        return {
            "message": "Materialized view ROUTE_REVENUE_MV refreshed successfully via DBMS_MVIEW.REFRESH.",
            "refreshed_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"MV refresh error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/admin/analytics/sql-explanations", tags=["Admin Analytics"])
def get_sql_explanations_endpoint():
    """
    Returns SQL query text, function explanations, and purposes for interactive "View SQL" expanders.
    """
    return db.SQL_EXPLANATIONS


# ====================================================================
# ENTRYPOINT
# ====================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)

