"""Shared fixtures.

The environment is set up before `backend` is imported anywhere: config.py
raises at import time when HOOPAI_SECRET_KEY is missing, which is the whole
point of it, and that makes import order load-bearing in the test suite too.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("HOOPAI_SECRET_KEY", secrets.token_urlsafe(48))
os.environ.setdefault("HOOPAI_JOB_WORKERS", "0")  # no pipeline subprocesses in tests


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient backed by a database, upload tree, and queue unique to the test."""
    import queue as _queue_mod

    from fastapi.testclient import TestClient

    from backend import config, jobs

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "hoopai.db")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "HIGHLIGHTS_DIR", tmp_path / "highlights")

    # The job queue is a module-level singleton sized at import. With no
    # workers draining it (HOOPAI_JOB_WORKERS=0 above), submissions accumulate
    # across the whole session and the ninth upload in the suite gets a 429
    # from a queue the test never filled. Give each test its own.
    monkeypatch.setattr(jobs, "_queue", _queue_mod.Queue(maxsize=config.JOB_QUEUE_SIZE))

    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_user(client):
    """Register an account and return (email, bearer-token)."""
    counter = {"n": 0}

    def _make(password: str = "correct-horse-battery") -> tuple[str, str]:
        counter["n"] += 1
        email = f"student{counter['n']}@example.com"
        response = client.post("/auth/signup", json={"email": email, "password": password})
        assert response.status_code == 201, response.text
        return email, response.json()["token"]

    return _make


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
