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

    Be clear about the cost of that choice: raising here means a typo in an
    optional mail key stops the whole API, not just outbound mail. It is the
    right trade anyway, because the failure lands on the operator running the
    deploy — who is watching, and whose fix is one line of .env — rather than
    on a student weeks later wondering why no mail arrived. Blank remains the
    way to say "off"; this error only fires on a value that was meant to be a
    key and is not one.
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


def _bool(name: str, default: bool) -> bool:
    """Read a flag, refusing anything that is not plainly true or false.

    No silent coercion. The obvious `bool(os.environ.get(name))` makes the
    string "false" mean true, and a flag that reads its own value backwards is
    worse than having no flag at all. An unrecognised value therefore stops the
    process rather than picking a side, because the two readings of a typo here
    differ by whether the API boots.
    """
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(
        f"{name} must be one of 1/0, true/false, yes/no, on/off (got {raw!r})."
    )


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

# -- Pipeline tuning ----------------------------------------------------------
# On a CPU-only host, running YOLO on every frame of a 90-minute game pins a
# core for a very long time. Sampling every Nth frame trades a small chance of
# missing a very short basket event for a proportional reduction in runtime.
# A basket takes ~2–4 seconds; at 30 fps that is 60–120 frames. Sampling every
# 3rd frame still checks 20–40 frames per basket — more than enough to catch it.
# Set to 1 to disable sampling (every frame). On a GPU host, 1 is fine; on the
# shared VPS, 3 is a reasonable default that keeps single-job time under 10 min
# for a typical varsity game.
FRAME_SAMPLE = _int("HOOPAI_FRAME_SAMPLE", 3)

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
# API key for Resend, read by `_send_verification_email` in routers/auth.py.
#
# Optional, and None when unset: a student running the API on a laptop has to
# boot without a mail provider, so a missing key leaves signup working and lets
# the account through unverified. Refusing every signup over a configuration
# detail would take the whole class down.
#
# That tolerance is also how this went wrong once already, so it is worth
# stating what it costs. The key was absent in production across three real
# signups. `_send_verification_email` did exactly what it is written to do —
# logged a warning and returned — signup still answered 201, and nothing else
# in the system knew that no verification mail had ever been sent. Hence the
# two additions below: production opts out of the tolerance (REQUIRE_EMAIL),
# and the mode is no longer something you have to go looking for (main.py logs
# it at startup and reports it on /health).
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

# Whether outbound mail is available at all. Everything that only needs to know
# "is mail on" reads this instead of the key, so that answering the question on
# /health or in a log line never involves handling the credential.
EMAIL_ENABLED = RESEND_API_KEY is not None

# The envelope sender. Here rather than inline in auth.py so that the
# post-deploy check (scripts/smoke_email.py) probes the same address production
# sends from. A check written against its own copy of this string would pass
# happily while the real sending domain was unverified, which is the single
# thing that check exists to catch.
#
# The domain must be a verified sender in the Resend dashboard. It is not
# verified by anything on this side: Resend answers an unverified domain with a
# 403 at send time, which auth.py logs and swallows.
EMAIL_FROM = (
    os.environ.get("HOOPAI_EMAIL_FROM", "").strip() or "HoopAI <noreply@hoopai.ithacateens.com>"
)

# Turn the missing-key tolerance off. Set this in the production environment and
# nowhere else: with it on, a deploy that forgets the key fails during import —
# loudly, in front of the operator who is watching the deploy and whose fix is
# one line of .env — instead of starting an API that passes its healthcheck and
# sends nothing.
#
# Deliberately checked at import rather than at the first send. A check at send
# time happens on a code path no deploy exercises, after a real user is already
# waiting for mail that is not coming.
REQUIRE_EMAIL = _bool("HOOPAI_REQUIRE_EMAIL", False)
if REQUIRE_EMAIL and not EMAIL_ENABLED:
    raise ConfigError(
        "HOOPAI_REQUIRE_EMAIL is set, so outbound email is mandatory here, but "
        "HOOPAI_RESEND_API_KEY is unset or empty. Put the key in the environment "
        "(on the server: apps/hoopai/.env.extra), or unset HOOPAI_REQUIRE_EMAIL "
        "to run without mail — signups are then let through unverified."
    )
