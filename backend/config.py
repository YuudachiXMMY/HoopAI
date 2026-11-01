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

from __future__ import annotations

import os
import re
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


def _optional_secret(name: str, prefix: str) -> str | None:
    """Read an optional API credential, returning None when it is not set.

    Unset means "the feature needing it is switched off", never "fall back to a
    default". There is no usable default for somebody else's API key, and
    inventing one turns a missing setting into a 401 from a third party, which
    is a much harder thing to read than a None.

    The prefix check is here because the alternative failure is invisible: a
    value truncated by a stray shell quote is accepted happily at this point
    and only shows up later as mail that never arrives, with no error anywhere
    on this side. Note that the value is deliberately left out of the message —
    a ConfigError goes to stderr and into the container log.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    if not value.startswith(prefix):
        raise ConfigError(
            f"{name} does not begin with {prefix!r}, so it cannot be a usable key. "
            f"Leave it unset to run without outbound email; a placeholder value here "
            f"would look configured and fail only at send time."
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


def _origin_regex(name: str) -> str | None:
    """Read the optional CORS origin pattern and return it anchored.

    `None` when unset, which is what disables regex matching entirely.

    Two things happen here rather than being left to whoever writes the value,
    because this pattern decides which websites a browser will let read our
    replies:

    1. **It must compile.** Otherwise the first browser request is a 500, long
       after the deploy reported success.
    2. **It is wrapped in `\\A(?:...)\\Z`**, so it can only ever match a whole
       origin. Unwrapped, `https://[a-z0-9-]+\\.figma\\.site` would also admit
       `https://x.figma.site.attacker.example` — a stranger's own domain
       holding a valid `Access-Control-Allow-Origin`.

       Starlette already prevents that by itself, and the wrap is belt and
       braces rather than a fix for a live hole. Stated that way because it was
       measured rather than assumed: `requirements-api.txt` gives
       `fastapi>=0.115.0` with no upper bound, so the question is what the
       whole range does, and `starlette/middleware/cors.py` matches with
       `re.fullmatch` (which anchors implicitly) in 0.21.0, 0.26.1, 0.37.2,
       0.38.6 and 1.10.0 — while `fastapi>=0.115.0` cannot resolve below
       `starlette>=0.37.2` in any case. There is no reachable version that
       anchors only one end.

       It is kept anyway because it is one f-string, and it makes the anchoring
       a local property of this file instead of an inherited habit of a
       transitive dependency that nothing here would notice changing.

    A consequence worth knowing when writing the value: it does not need to
    carry its own `^`/`$`. Including them is harmless and reads more obviously.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None

    anchored = rf"\A(?:{raw})\Z"
    try:
        re.compile(anchored)
    except re.error as exc:
        # A *global* inline flag is only legal at the very start of a pattern,
        # so `(?i)https://...` compiles alone and then dies once wrapped. Say
        # so, because re's own "global flags not at the start of the
        # expression" reads like a bug in here rather than something to change
        # in the environment.
        if re.match(r"\(\?[aiLmsux]+\)", raw):
            raise ConfigError(
                f"{name} may not open with a global inline flag such as (?i): this value "
                f"is wrapped to match a whole origin, which moves the flag off the front. "
                f"Use a scoped group instead — (?i:...).\n"
                f"    got: {raw}"
            ) from exc
        raise ConfigError(
            f"{name} is not a valid regular expression: {exc}\n    got: {raw}"
        ) from exc

    return anchored


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

# For origins that cannot be enumerated ahead of time. The front-end students
# build is published on Figma's hosting, which assigns each published site its
# own randomly generated subdomain. Two things follow, and together they are
# why this is a pattern and not a longer list: a list needs one entry per
# student, and a student can change their own subdomain from their file's
# Settings — the old one stops working the moment they do, with nothing on
# this side told about it. A student whose login broke that way has no way to
# tell it from the API being down.
#
# (Republishing does NOT reassign it — Figma reuses the same domain, including
# across an unpublish. An earlier version of this comment claimed otherwise.)
#
#   HOOPAI_CORS_ORIGIN_REGEX=^https://[a-z0-9-]+\.figma\.site$
#
# Unset by default: nothing is admitted by pattern unless someone asks for it.
# Prefer a specific character class over `.*` or `.+`, which also match `/`,
# `@`, `#` and `?` — see the Starlette CORSMiddleware docs.
#
# Be clear-eyed about what that example value grants. `figma.site` is shared
# hosting anyone can publish to, so the pattern admits a stranger's page as
# readily as a student's — the same class of decision as allow-listing
# `*.github.io`. What keeps it a small grant here is the line below it in
# add_cors(): credentials are off and auth is a Bearer header, so an admitted
# origin gets calls that any machine with a network connection could already
# make, and not the ability to act as a logged-in student. Should this API ever
# move to cookie auth, this setting has to be revisited first.
CORS_ORIGIN_REGEX = _origin_regex("HOOPAI_CORS_ORIGIN_REGEX")

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

# The other end of the range, and the one that was missing. With no floor, a
# 0-byte .mp4 is a free jobs row and a free directory: it never fills the queue
# (it drains instantly, so the 429 never fires) and it costs the sender
# nothing. A loop of them is inode exhaustion on a filesystem shared with six
# other applications. 1 KiB is below any real video and above any empty one.
MIN_UPLOAD_BYTES = _int("HOOPAI_MIN_UPLOAD_BYTES", 1024)

# Stored jobs per account. Signup is open, so "one student, one folder of
# footage" has to be enforced rather than assumed. Generous enough for a term
# of coursework; finite, which is the point.
MAX_JOBS_PER_USER = _int("HOOPAI_MAX_JOBS_PER_USER", 50)

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

# -- Outbound email -----------------------------------------------------------
# API key for Resend, read for the email-verification flow.
#
# NOTHING IN THIS REPOSITORY READS IT YET. There is no mail-sending code and no
# verification state in backend/ — signup inserts a row and returns a token, and
# `EmailStr` on the request model checks the shape of an address, not that it
# exists. So setting this today only makes the value reachable as
# `config.RESEND_API_KEY`; it exists ahead of the feature so that the deploy can
# already be carrying the key when the feature lands.
#
# Optional, and None when unset: a student running the API on a laptop has to
# boot without a mail provider. Whatever sends mail later therefore has to
# handle None rather than assume a string, and decide explicitly what "no mail
# provider" means. Let signup through unverified — refusing every signup
# because a key is missing takes the whole class down for a configuration
# detail.
#
# Never given a default and never committed. This is a bearer credential for an
# account that can send mail AS our domain, so a literal in the source is a
# published ability to send mail as us — the same mistake as the old hardcoded
# SECRET_KEY, with phishing rather than forged sessions on the other end of it.
# Local value goes in .env; on the server it goes in apps/hoopai/.env.extra.
# Rotate it in the Resend dashboard the moment it is pasted into a chat, a
# screen share, or a terminal recording: unlike SECRET_KEY, rotating costs
# nothing here, because no stored state is keyed to it.
RESEND_API_KEY = _optional_secret("HOOPAI_RESEND_API_KEY", "re_")
