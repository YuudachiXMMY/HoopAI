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


@asynccontextmanager
async def lifespan(_: FastAPI):
    # `@app.on_event("startup")` is deprecated and, more to the point, had no
    # shutdown counterpart — the worker threads below need one.
    init_db()
    jobs.fail_orphaned_jobs()
    jobs.start_workers()
    yield
    jobs.stop_workers()


app = FastAPI(title="HoopAI API", lifespan=lifespan)

# Was allow_origins=["*"] with allow_credentials=True — a combination browsers
# reject outright, so the policy never worked and nobody noticed how open it
# was meant to be. Credentials are off because this API authenticates with a
# Bearer header, not a cookie, so no cross-origin credential is needed; with
# them off, `*` would in fact be safe, but an explicit list costs nothing and
# keeps an unexpected browser client from quietly becoming a supported one.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

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
    """
    return {"status": "ok", "queue_depth": jobs.depth(), "queue_size": config.JOB_QUEUE_SIZE}
