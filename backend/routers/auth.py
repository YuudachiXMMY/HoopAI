"""Signup and login."""

from __future__ import annotations

import logging
import secrets
import sqlite3
import time

import httpx
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


class VerifyResponse(BaseModel):
    message: str


_VERIFICATION_TTL_SECONDS = 24 * 3600  # tokens expire after 24 hours


def _normalise(email: str) -> str:
    return email.strip().lower()


def _send_verification_email(to_email: str, token: str) -> None:
    """Send a verification email via Resend. No-op if RESEND_API_KEY is unset."""
    api_key = config.RESEND_API_KEY
    if not api_key:
        log.warning("RESEND_API_KEY not set — skipping verification email for %s", to_email)
        return

    verify_url = f"https://hoopai.ithacateens.com/auth/verify/{token}"
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": "HoopAI <noreply@hoopai.ithacateens.com>",
                "to": [to_email],
                "subject": "Verify your HoopAI account",
                "html": (
                    f"<p>Welcome to HoopAI!</p>"
                    f"<p>Click the link below to verify your email address. "
                    f"The link expires in 24 hours.</p>"
                    f"<p><a href='{verify_url}'>{verify_url}</a></p>"
                ),
            },
            timeout=10.0,
        )
        if resp.status_code >= 400:
            log.error("Resend API error %s: %s", resp.status_code, resp.text)
        else:
            log.info("verification email sent to %s", to_email)
    except Exception:
        log.exception("failed to send verification email to %s", to_email)


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(data: Credentials) -> TokenResponse:
    email = _normalise(data.email)

    # Hashed BEFORE the connection is opened. argon2 takes tens of
    # milliseconds and is serialised behind a semaphore, so doing it inside the
    # block would hold an open SQLite connection for the whole wait.
    password_hash = hash_password(data.password)

    with connection() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO users (email, password_hash, verified) VALUES (?, ?, 0)",
                (email, password_hash),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That email is already registered.",
            ) from None

        user_id = cursor.lastrowid
        token = secrets.token_urlsafe(32)
        expires_at = time.time() + _VERIFICATION_TTL_SECONDS
        conn.execute(
            "INSERT INTO verification_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires_at),
        )

    log.info("signup: user %s", user_id)
    _send_verification_email(email, token)
    return TokenResponse(token=create_token(user_id, email), email=email)


@router.get("/verify/{token}", response_model=VerifyResponse)
def verify_email(token: str) -> VerifyResponse:
    now = time.time()
    with connection() as conn:
        row = conn.execute(
            "SELECT user_id, expires_at FROM verification_tokens WHERE token = ?",
            (token,),
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid or already-used verification link.")
        if row["expires_at"] < now:
            conn.execute("DELETE FROM verification_tokens WHERE token = ?", (token,))
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="This verification link has expired. Please sign up again.")

        conn.execute("UPDATE users SET verified = 1 WHERE id = ?", (row["user_id"],))
        conn.execute("DELETE FROM verification_tokens WHERE token = ?", (token,))
        log.info("email verified: user %s", row["user_id"])

    return VerifyResponse(message="Email verified. You can now log in.")


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest) -> TokenResponse:
    email = _normalise(data.email)
    now = time.time()

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        # One message for "no such account" and for "wrong password", and (see
        # below) one response time for both.
        #
        # THIS DOES NOT MAKE ACCOUNT ENUMERATION IMPOSSIBLE, only harder here.
        # `/auth/signup` still answers 409 for an address that already exists,
        # which is a cleaner oracle than anything this endpoint leaks — POST a
        # list of firstname.lastname@school.tld and read off the hits. Closing
        # that needs an email-verification step, i.e. a feature rather than a
        # patch; until then, assume an attacker can learn who has an account
        # and note that the per-account lockout below is consequently a
        # targeted denial-of-service primitive against any address they
        # confirm.
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
            "SELECT id, email, password_hash, failed_logins, locked_until, verified FROM users WHERE email = ?",
            (email,),
        ).fetchone()

        if user is None:
            waste_time_like_a_real_verify()
            outcome, retry_after = "unknown", 0
        elif not user["verified"]:
            outcome, retry_after = "unverified", 0
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

    if outcome == "unverified":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in. Check your inbox for the verification link.",
        )
    if outcome == "locked":
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
    if outcome != "ok":
        raise invalid

    return TokenResponse(token=create_token(user["id"], user["email"]), email=user["email"])
