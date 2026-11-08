"""HoopAI API application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import config, jobs
from backend.database import init_db
from backend.routers import auth, video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)
log = logging.getLogger("hoopai")


def log_email_mode() -> None:
    """State on every boot whether outbound mail is on, and who it sends as.

    Here and not in config.py because of an import-order detail that would make
    the line vanish: `from backend import config` above runs before the
    `basicConfig` call below it, so a log record emitted while config is being
    imported goes to logging's handler of last resort, which drops anything
    below WARNING. The ENABLED line would therefore be silently missing in the
    exact case it is meant to confirm.

    Why it exists at all: mail was off in production for three real signups and
    the only trace was one WARNING per signup, buried among healthcheck lines
    and only findable by someone who already suspected it. A line at startup is
    greppable at a known place, once per restart, without that suspicion.
    """
    if config.EMAIL_ENABLED:
        log.info("outbound email: ENABLED (resend, from=%s)", config.EMAIL_FROM)
    else:
        log.warning(
            "outbound email: DISABLED (HOOPAI_RESEND_API_KEY unset) — signups are "
            "let through unverified. Set HOOPAI_REQUIRE_EMAIL=1 to make this fatal."
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    # `@app.on_event("startup")` is deprecated and, more to the point, had no
    # shutdown counterpart — the worker threads below need one.
    log_email_mode()
    init_db()
    jobs.fail_orphaned_jobs()
    jobs.start_workers()
    yield
    jobs.stop_workers()


app = FastAPI(title="HoopAI API", lifespan=lifespan)


def add_cors(target: FastAPI) -> None:
    """Install the CORS policy, reading it from `config` at call time.

    A function rather than a bare `add_middleware` call so the policy can be
    exercised in a test without re-importing this module — the settings are
    read once at import, so a test that monkeypatches them afterwards would be
    asserting against middleware that was already built. Production and the
    tests therefore go through this one definition and cannot drift apart.

    Was allow_origins=["*"] with allow_credentials=True — a combination
    browsers reject outright, so the policy never worked and nobody noticed how
    open it was meant to be. Credentials stay off because this API
    authenticates with a Bearer header, not a cookie: a browser will not attach
    one cross-origin, so admitting an origin grants it calls that anything with
    a network connection could already make, and not the ability to act as a
    logged-in student. That is what makes `CORS_ORIGIN_REGEX` tolerable.
    """
    target.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_origin_regex=config.CORS_ORIGIN_REGEX,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )


add_cors(app)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(video.router, prefix="/video", tags=["video"])


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "HoopAI API is running"}


@app.get("/health")
def health() -> dict[str, object]:
    """Liveness for the container healthcheck and Uptime Kuma.

    Reports queue depth as information, not as a verdict: a full queue is the
    backpressure design working, and a healthcheck that failed on it would
    have Docker restart the container precisely when it is busiest — killing
    the job that is mid-flight.

    `email` is reported for the same reason and with the same status: it is
    information, and "disabled" is still `"status": "ok"` because an API with
    no mail provider is a working API. It is here so that "is verification
    mail actually on in production?" is one unauthenticated request rather
    than an ssh session and a log grep — which is what it took last time, by
    which point three signups had already been missed. Never the key itself,
    only whether there is one.
    """
    return {
        "status": "ok",
        "queue_depth": jobs.depth(),
        "queue_size": config.JOB_QUEUE_SIZE,
        "email": "configured" if config.EMAIL_ENABLED else "disabled",
    }
