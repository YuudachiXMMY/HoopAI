# HoopAI API + pipeline.
#
# One image runs both: the API serves requests and its worker thread shells out
# to hoopal.py in the same filesystem. Splitting them would be the better shape
# once the queue is durable (see backend/jobs.py), but two containers sharing an
# in-process queue is not a design, so they stay together for now.

FROM python:3.12-slim AS base

# OpenCV and the clip exporter need these; the slim image has neither.
# libgl1/libglib2.0-0 are cv2's runtime link dependencies — without them the
# import fails at startup with a message that does not mention OpenCV.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a source edit does not re-resolve torch.
COPY requirements.txt requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-api.txt

COPY backend/ ./backend/
COPY ingest/ ./ingest/
COPY detect/ ./detect/
COPY events/ ./events/
COPY clips/ ./clips/
COPY hoopal.py ./

# -- Non-root ----------------------------------------------------------------
# Defence in depth rather than the primary control: the compose file sets
# no-new-privileges and the host never grants this container capabilities. What
# this buys is that a bug in the upload path — or an instructor with a shell —
# is not writing as uid 0 onto a volume shared with the host's uid namespace.
#
# uid 10001 is arbitrary but fixed: the volumes below are chowned to it, and a
# number that changes between builds silently breaks an existing deployment.
RUN useradd --system --uid 10001 --create-home --home-dir /home/hoopai hoopai

# Writable state lives here and nowhere else; everything above is read-only to
# the running process. These are the mount points the compose file attaches a
# named volume to — created and chowned now so the first start does not depend
# on Docker's volume-seeding behaviour.
RUN mkdir -p /data/db /data/uploads /data/highlights /models \
    && chown -R hoopai:hoopai /data

ENV HOOPAI_DB_PATH=/data/db/hoopai.db \
    HOOPAI_UPLOAD_DIR=/data/uploads \
    HOOPAI_HIGHLIGHTS_DIR=/data/highlights \
    HOOPAI_PIPELINE_ROOT=/app \
    HOOPAI_MODEL_PATH=/models/basketball.pt

USER hoopai

EXPOSE 8000

# Matches the compose healthcheck. Kept here too so `docker run` without
# compose still reports health.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# One uvicorn worker, deliberately. Each worker is a separate process with its
# own in-process job queue, so N workers would mean N times the configured
# concurrency reaching the pipeline — quietly undoing the cap that exists to
# keep this app from taking the shared host down. Scale by raising
# HOOPAI_JOB_WORKERS, which the queue actually accounts for.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
