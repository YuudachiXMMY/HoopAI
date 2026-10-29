"""Configuration must refuse to start rather than fall back to a weak default.

This file is why the repository can be public. Every assertion here is "the
process stops" — the alternative, a default signing key, is a published
credential, and a published signing key means anyone can mint a token for any
account.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _import_config_with(env: dict[str, str]):
    """Import backend.config in a clean interpreter with exactly this env."""
    script = "import backend.config as c; print(c.SECRET_KEY)"
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO_ROOT), **env},
        capture_output=True,
        text=True,
    )


def test_a_missing_secret_key_stops_the_process():
    result = _import_config_with({})
    assert result.returncode != 0
    assert "HOOPAI_SECRET_KEY" in result.stderr


def test_a_short_secret_key_stops_the_process():
    result = _import_config_with({"HOOPAI_SECRET_KEY": "x"})
    assert result.returncode != 0
    assert "characters" in result.stderr


def test_an_adequate_secret_key_imports():
    result = _import_config_with({"HOOPAI_SECRET_KEY": "k" * 48})
    assert result.returncode == 0, result.stderr


def test_the_published_literal_is_gone_from_the_source():
    """Belt and braces: grep the tree for the key that was committed.

    The constant was duplicated across auth.py and video.py, so deleting one
    copy and believing the job done is a live failure mode.
    """
    offenders = []
    for path in (REPO_ROOT / "backend").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        # tests/ legitimately references it to prove it is rejected.
        if "hoopai-secret-change-in-production" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"hardcoded signing key still present in: {offenders}"


def test_cors_is_not_a_wildcard():
    from backend import config

    assert "*" not in config.CORS_ORIGINS


@pytest.mark.parametrize("name", ["JOB_WORKERS", "JOB_QUEUE_SIZE", "MAX_UPLOAD_BYTES"])
def test_the_host_protecting_limits_are_finite(name):
    from backend import config

    importlib.reload  # keep the import meaningful to linters
    value = getattr(config, name)
    assert isinstance(value, int) and value >= 0
