"""Runtime configuration, read once from the environment.

Everything that used to be a module-level literal in auth.py and video.py lives
here instead, for one reason: this repository is public. A constant named
SECRET_KEY in a public repo is not a secret, it is a published signing key, and
anyone who reads it can mint a token for any account. So the signing key has no
default at all — a missing HOOPAI_SECRET_KEY stops the process at import time
rather than starting a server that trusts forged tokens.

The paths and limits below do have defaults, because getting them wrong is a
bug rather than a breach, and a student running the API on a laptop should not
need a six-line .env to see it boot.
"""

import os
from pathlib import Path

# Smallest key we will accept. 32 bytes is the HMAC-SHA256 block-size-adjacent
# figure everyone quotes; the point of enforcing it is narrower than that —
# it stops someone "satisfying" the missing-key error with HOOPAI_SECRET_KEY=x
# and ending up exactly where the hardcoded literal left us.
MIN_SECRET_LENGTH = 32


class ConfigError(RuntimeError):
    """Raised at import time when a required setting is missing or unusable."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} is not set. Generate one with:\n"
            f"    python -c 'import secrets; print(secrets.token_urlsafe(48))'\n"
            f"and put it in your .env (never in the repository)."
        )
    return value


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _list(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, "").strip() or default
    return [item.strip() for item in raw.split(",") if item.strip()]


# -- Signing key --------------------------------------------------------------
SECRET_KEY = _require("HOOPAI_SECRET_KEY")
if len(SECRET_KEY) < MIN_SECRET_LENGTH:
    raise ConfigError(
        f"HOOPAI_SECRET_KEY is only {len(SECRET_KEY)} characters; "
        f"at least {MIN_SECRET_LENGTH} are required."
    )

JWT_ALGORITHM = "HS256"
TOKEN_TTL_HOURS = _int("HOOPAI_TOKEN_TTL_HOURS", 12)

# -- CORS ---------------------------------------------------------------------
# The previous value was allow_origins=["*"] together with
# allow_credentials=True. Browsers reject that combination outright, so the
# setting was not merely permissive, it did not work — which is why nobody
# noticed it was permissive. An explicit list is both correct and narrow.
CORS_ORIGINS = _list("HOOPAI_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")

# -- Storage ------------------------------------------------------------------
# Defaults point inside the package for local use. In the container these are
# set to a mounted volume, so that `docker compose up` on a rebuilt image does
# not start with an empty user table.
_DEFAULT_ROOT = Path(__file__).resolve().parent

DB_PATH = Path(os.environ.get("HOOPAI_DB_PATH", _DEFAULT_ROOT / "hoopai.db"))
UPLOAD_DIR = Path(os.environ.get("HOOPAI_UPLOAD_DIR", _DEFAULT_ROOT / "uploads"))
HIGHLIGHTS_DIR = Path(os.environ.get("HOOPAI_HIGHLIGHTS_DIR", _DEFAULT_ROOT / "highlights"))

# Where hoopal.py and its model weights live. Separate from the dirs above
# because the code is read-only and baked into the image, while the three
# above are writable state on a volume.
PIPELINE_ROOT = Path(os.environ.get("HOOPAI_PIPELINE_ROOT", _DEFAULT_ROOT.parent))
MODEL_PATH = Path(os.environ.get("HOOPAI_MODEL_PATH", PIPELINE_ROOT / "data/models/basketball.pt"))

# -- Upload limits ------------------------------------------------------------
# The old handler did `content = await file.read()` with no ceiling: one student
# uploading a 4 GB phone video was an OOM kill of the API for everyone. The
# handler now streams, and stops at this many bytes.
MAX_UPLOAD_BYTES = _int("HOOPAI_MAX_UPLOAD_MB", 512) * 1024 * 1024

# Extension allow-list. Deliberately not a MIME check on the client-supplied
# Content-Type, which is attacker-controlled and means nothing. This is a cheap
# first gate; ffmpeg/OpenCV failing to decode is the real one.
ALLOWED_VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"})

# -- Job queue ----------------------------------------------------------------
# This is the setting that protects the host rather than the app. The pipeline
# is YOLO inference over every frame of a video; on the shared VPS this is
# deployed to, one run saturates a core for minutes. The old code started a
# thread AND a subprocess per upload with no ceiling, so N simultaneous
# students meant N concurrent YOLO processes and a box that stops answering —
# including for the other applications hosted beside it.
#
# One worker, a short queue, and an explicit 429 when the queue is full. A
# student who is refused can retry; a host that has fallen over cannot.
JOB_WORKERS = _int("HOOPAI_JOB_WORKERS", 1)
JOB_QUEUE_SIZE = _int("HOOPAI_JOB_QUEUE_SIZE", 8)
JOB_TIMEOUT_SECONDS = _int("HOOPAI_JOB_TIMEOUT_SECONDS", 1800)

# -- Auth throttling ----------------------------------------------------------
# Not a substitute for a real rate limiter at the edge (see the note in
# IthacaServer's middlewares.yml about source IPs behind Cloudflare). This
# counts failures per ACCOUNT, which is the dimension a shared-IP limiter
# cannot see, and is the one that matters for password guessing.
LOGIN_MAX_FAILURES = _int("HOOPAI_LOGIN_MAX_FAILURES", 10)
LOGIN_LOCKOUT_SECONDS = _int("HOOPAI_LOGIN_LOCKOUT_SECONDS", 900)

# Minimum password length at signup. Low enough not to fight students over it,
# high enough that the argon2 cost actually matters.
MIN_PASSWORD_LENGTH = _int("HOOPAI_MIN_PASSWORD_LENGTH", 10)
