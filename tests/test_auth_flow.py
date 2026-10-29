"""Signup, login, password storage, and lockout."""

from __future__ import annotations

import pytest


def test_signup_then_login(client):
    signup = client.post("/auth/signup", json={"email": "a@example.com", "password": "correct-horse"})
    assert signup.status_code == 201

    login = client.post("/auth/login", json={"email": "a@example.com", "password": "correct-horse"})
    assert login.status_code == 200
    assert login.json()["token"]


def test_email_is_matched_case_insensitively(client):
    client.post("/auth/signup", json={"email": "Alice@Example.COM", "password": "correct-horse"})
    assert client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "correct-horse"}
    ).status_code == 200


def test_a_duplicate_signup_is_a_409_not_a_generic_400(client):
    body = {"email": "a@example.com", "password": "correct-horse"}
    assert client.post("/auth/signup", json=body).status_code == 201
    assert client.post("/auth/signup", json=body).status_code == 409


@pytest.mark.parametrize("email", ["not-an-email", "@example.com", "a@", ""])
def test_signup_rejects_a_malformed_email(client, email):
    """EmailStr was imported and never used, so anything was a valid account."""
    assert client.post("/auth/signup", json={"email": email, "password": "correct-horse"}).status_code == 422


def test_signup_rejects_a_short_password(client):
    assert client.post("/auth/signup", json={"email": "a@example.com", "password": "abc"}).status_code == 422


def test_wrong_password_and_unknown_account_are_indistinguishable(client):
    """Otherwise /auth/login enumerates who has an account here."""
    client.post("/auth/signup", json={"email": "a@example.com", "password": "correct-horse"})

    wrong = client.post("/auth/login", json={"email": "a@example.com", "password": "wrong-password"})
    unknown = client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_unknown_and_known_accounts_take_comparable_time(client):
    """Identical error bodies are not enough if the clock gives it away.

    argon2 is deliberately tens of milliseconds. Skipping it for an email that
    is not in the table makes "no such account" measurably faster than "wrong
    password", which rebuilds the enumeration oracle the shared message
    removes. The fix is a dummy verify on the unknown branch.

    The tolerance is loose on purpose — this is a shared CI machine, not a lab
    bench. It is sized to catch the real regression (one branch skipping argon2
    entirely, a several-fold difference) and not to be flaky about scheduler
    noise. A tight threshold here would be turned off within a month.
    """
    import statistics
    import time

    client.post("/auth/signup", json={"email": "known@example.com", "password": "correct-horse"})

    def timed(email: str) -> float:
        samples = []
        for _ in range(5):
            start = time.perf_counter()
            client.post("/auth/login", json={"email": email, "password": "wrong-password-here"})
            samples.append(time.perf_counter() - start)
        return statistics.median(samples)

    known = timed("known@example.com")
    unknown = timed("nobody@example.com")

    ratio = max(known, unknown) / max(min(known, unknown), 1e-9)
    assert ratio < 3.0, (
        f"login timing distinguishes a known account ({known * 1000:.1f} ms) from an "
        f"unknown one ({unknown * 1000:.1f} ms), ratio {ratio:.1f}x — the unknown branch "
        "is probably skipping the password verification"
    )


def test_passwords_are_not_stored_as_unsalted_sha256(client):
    """The original stored `hashlib.sha256(password).hexdigest()`.

    Unsalted, so two students with the same password had identical rows, and
    fast, so a leaked table is a wordlist lookup rather than a cracking job.
    """
    import hashlib

    from backend import config
    from backend.database import connection

    password = "correct-horse"
    client.post("/auth/signup", json={"email": "a@example.com", "password": password})

    with connection() as conn:
        stored = conn.execute("SELECT password_hash FROM users").fetchone()["password_hash"]

    assert stored != hashlib.sha256(password.encode()).hexdigest()
    assert password not in stored
    assert stored.startswith("$argon2")
    assert config.DB_PATH.exists()


def test_the_same_password_hashes_differently_for_two_users(client):
    from backend.database import connection

    for name in ("a", "b"):
        client.post("/auth/signup", json={"email": f"{name}@example.com", "password": "correct-horse"})

    with connection() as conn:
        hashes = [row["password_hash"] for row in conn.execute("SELECT password_hash FROM users")]

    assert len(set(hashes)) == 2, "identical passwords produced identical hashes — the salt is missing"


def test_an_account_locks_after_repeated_failures(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "LOGIN_MAX_FAILURES", 3)
    client.post("/auth/signup", json={"email": "a@example.com", "password": "correct-horse"})

    for _ in range(3):
        assert client.post(
            "/auth/login", json={"email": "a@example.com", "password": "wrong-password"}
        ).status_code == 401

    locked = client.post("/auth/login", json={"email": "a@example.com", "password": "correct-horse"})
    assert locked.status_code == 429
    assert "Retry-After" in locked.headers


def test_a_successful_login_clears_the_failure_count(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "LOGIN_MAX_FAILURES", 3)
    client.post("/auth/signup", json={"email": "a@example.com", "password": "correct-horse"})

    for _ in range(2):
        client.post("/auth/login", json={"email": "a@example.com", "password": "wrong-password"})
    assert client.post(
        "/auth/login", json={"email": "a@example.com", "password": "correct-horse"}
    ).status_code == 200

    # Two more failures must not trip the lock, because the counter reset.
    for _ in range(2):
        assert client.post(
            "/auth/login", json={"email": "a@example.com", "password": "wrong-password"}
        ).status_code == 401
    assert client.post(
        "/auth/login", json={"email": "a@example.com", "password": "correct-horse"}
    ).status_code == 200
