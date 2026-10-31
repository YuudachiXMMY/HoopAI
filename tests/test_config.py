"""Configuration must refuse to start rather than fall back to a weak default.

This file is why the repository can be public. Every assertion here is "the
process stops" — the alternative, a default signing key, is a published
credential, and a published signing key means anyone can mint a token for any
account.
"""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _import_config_with(env: dict[str, str], expr: str = "c.SECRET_KEY"):
    """Import backend.config in a clean interpreter with exactly this env.

    A subprocess rather than `importlib.reload`, because the settings are read
    once at import and the assertions here are all about what happens *during*
    that import — a reload in this interpreter would be fighting whatever
    conftest.py already put in `os.environ`.
    """
    script = f"import backend.config as c; print({expr})"
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


# -- The CORS origin regex ----------------------------------------------------
#
# `_origin_regex` returns the pattern the middleware is actually given, which
# is not the string the environment supplied: it is wrapped in \A(?:...)\Z so
# it can only match a whole origin. These assert that property directly rather
# than through the middleware, deliberately — Starlette matches with
# `re.fullmatch`, which anchors implicitly, so a request-level test cannot tell
# a wrapped pattern from an unwrapped one. The wrap is what makes the anchoring
# true independently of that, and `re.match` below is what demonstrates it.

_KEY = {"HOOPAI_SECRET_KEY": "k" * 48}

ATTACKER_SUFFIX = "https://anything.figma.site.attacker.example"


def _origin_regex_for(value: str) -> str:
    """The effective pattern a fresh process builds from this env value."""
    result = _import_config_with(
        {**_KEY, "HOOPAI_CORS_ORIGIN_REGEX": value}, "c.CORS_ORIGIN_REGEX"
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_no_origin_regex_by_default():
    result = _import_config_with(_KEY, "c.CORS_ORIGIN_REGEX")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "None"


@pytest.mark.parametrize(
    "supplied",
    [
        # Anchored by hand, which is the documented example and the common case.
        r"^https://[a-z0-9-]+\.figma\.site$",
        # Not anchored at all. Accepted — the wrap is what anchors it, so the
        # environment is not required to get this right.
        r"https://[a-z0-9-]+\.figma\.site",
        # Anchored at the start only.
        r"^https://[a-z0-9-]+\.figma\.site",
        # A top-level alternation with one unanchored branch. The branch cannot
        # leak, because the wrap groups the alternation rather than sitting
        # inside one arm of it.
        r"^https://good\.example$|https://[a-z0-9-]+\.figma\.site",
    ],
)
def test_the_effective_pattern_matches_whole_origins_only(supplied):
    effective = _origin_regex_for(supplied)

    # `re.match` rather than `fullmatch` on purpose: `match` anchors only the
    # start, so it is the weaker semantics, and passing under it means the
    # pattern carries its own anchoring instead of borrowing the middleware's.
    assert re.match(effective, "https://thorn-snout-04735436.figma.site")
    assert re.match(effective, ATTACKER_SUFFIX) is None
    assert re.match(effective, "https://thorn-snout-04735436.figma.site\n") is None


def test_a_global_inline_flag_stops_the_process():
    """`(?i)` is legal only at the very start, so wrapping would invalidate it.

    Worth its own error: re's own message ("global flags not at the start of
    the expression") reads like a bug in config.py rather than something to
    change in the environment.
    """
    result = _import_config_with(
        {**_KEY, "HOOPAI_CORS_ORIGIN_REGEX": r"(?i)^https://[a-z0-9-]+\.figma\.site$"},
        "c.CORS_ORIGIN_REGEX",
    )
    assert result.returncode != 0
    assert "(?i:" in result.stderr


def test_an_uncompilable_origin_regex_stops_the_process():
    """Otherwise the first browser request is a 500, long after a green deploy."""
    result = _import_config_with(
        {**_KEY, "HOOPAI_CORS_ORIGIN_REGEX": r"^https://[a-z0-9-\.figma\.site$"},
        "c.CORS_ORIGIN_REGEX",
    )
    assert result.returncode != 0
    assert "HOOPAI_CORS_ORIGIN_REGEX" in result.stderr


@pytest.mark.parametrize("name", ["JOB_WORKERS", "JOB_QUEUE_SIZE", "MAX_UPLOAD_BYTES"])
def test_the_host_protecting_limits_are_finite(name):
    from backend import config

    importlib.reload  # keep the import meaningful to linters
    value = getattr(config, name)
    assert isinstance(value, int) and value >= 0
