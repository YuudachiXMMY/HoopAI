from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
import hashlib
import jwt
import datetime
from backend.database import get_connection

router = APIRouter()

SECRET_KEY = "hoopai-secret-change-in-production"


class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def create_token(user_id: int, email: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


@router.post("/signup")
def signup(data: SignupRequest):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (data.email, hash_password(data.password)),
        )
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (data.email,)).fetchone()
        token = create_token(user["id"], user["email"])
        return {"token": token, "email": user["email"]}
    except Exception:
        raise HTTPException(status_code=400, detail="Email already registered")
    finally:
        conn.close()


@router.post("/login")
def login(data: LoginRequest):
    conn = get_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ? AND password_hash = ?",
        (data.email, hash_password(data.password)),
    ).fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_token(user["id"], user["email"])
    return {"token": token, "email": user["email"]}
