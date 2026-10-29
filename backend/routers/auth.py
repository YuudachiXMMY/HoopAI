"""Signup and login."""

from __future__ import annotations

import logging
import sqlite3
import time

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from backend import config
from backend.database import connection
from backend.security import (
    create_token,
    hash_password,
    verify_password,
    waste_time_like_a_real_verify,
)

log = logging.getLogger("hoopai.auth")

router = APIRouter()


class Credentials(BaseModel):
    # EmailStr was imported but unused in the original, and `email` was a plain
    # str — so "not an email" was a valid account name.
    email: EmailStr
    password: str = Field(min_length=config.MIN_PASSWORD_LENGTH, max_length=1024)


class LoginRequest(BaseModel):
    email: EmailStr
    # No min_length on login: rejecting a short password here would tell an
    # attacker their guess was too short to be the real one, and it would lock
    # out any account created before the rule existed.
    password: str = Field(max_length=1024)


class TokenResponse(BaseModel):
    token: str
    email: str


def _normalise(email: str) -> str:
    return email.strip().lower()


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(data: Credentials) -> TokenResponse:
    email = _normalise(data.email)

    with connection() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, hash_password(data.password)),
            )
        except sqlite3.IntegrityError:
            # Narrowed from `except Exception`. The original reported EVERY
            # failure — a disk error, a schema mismatch, a bug in the hasher —
            # as "Email already registered", so the one error message a student
            # ever saw was frequently a lie and the real fault was invisible.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That email is already registered.",
            ) from None

        user_id = cursor.lastrowid

    log.info("signup: user %s", user_id)
    return TokenResponse(token=create_token(user_id, email), email=email)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest) -> TokenResponse:
    email = _normalise(data.email)
    now = time.time()

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        # One message for "no such account" and for "wrong password". Two
        # distinct messages would make this endpoint an account enumerator.
        detail="Invalid email or password.",
    )

    # NOTHING IN THIS FUNCTION RAISES INSIDE A `with connection()` BLOCK.
    #
    # `connection()` rolls back on any exception, HTTPException included. The
    # first version of this handler recorded the failed attempt and then raised
    # 401 from inside the block — so every increment and every lockout was
    # rolled back on its way out, and the throttle counted to one forever while
    # looking entirely correct in the source. The tests caught it; reading it
    # did not. Hence: decide inside the block, raise after it has committed.
    with connection() as conn:
        user = conn.execute(
            "SELECT id, email, password_hash, failed_logins, locked_until FROM users WHERE email = ?",
            (email,),
        ).fetchone()

        if user is None:
            # Spend a verification's worth of time anyway. The two branches
            # return the same body and the same status; without this they are
            # still told apart by how long they take, because argon2 is tens
            # of milliseconds and a dictionary lookup is not.
            waste_time_like_a_real_verify()
            outcome, retry_after = "unknown", 0
        elif (user["locked_until"] or 0) > now:
            outcome, retry_after = "locked", int(user["locked_until"] - now) + 1
        elif not verify_password(data.password, user["password_hash"]):
            failures = user["failed_logins"] + 1
            # Per-account, not per-IP. An IP limiter is the wrong tool here:
            # every request arrives via Cloudflare, so the edge sees one source
            # address for the whole internet (see the long note in
            # IthacaServer infrastructure/traefik/dynamic/middlewares.yml).
            # The account is the dimension that is actually observable.
            locks_now = failures >= config.LOGIN_MAX_FAILURES
            conn.execute(
                "UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
                (
                    0 if locks_now else failures,
                    now + config.LOGIN_LOCKOUT_SECONDS if locks_now else None,
                    user["id"],
                ),
            )
            if locks_now:
                log.warning("login: account %s locked after %d failures", user["id"], failures)
            outcome, retry_after = "wrong-password", 0
        else:
            conn.execute(
                "UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?",
                (user["id"],),
            )
            outcome, retry_after = "ok", 0

    if outcome == "locked":
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
    if outcome != "ok":
        raise invalid

    return TokenResponse(token=create_token(user["id"], user["email"]), email=user["email"])
