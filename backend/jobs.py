"""Bounded job queue for pipeline runs.

WHY THIS FILE REPLACES `threading.Thread(...).start()`

The original upload handler started a daemon thread per request, and that
thread started a `hoopal.py` subprocess. Nothing anywhere capped either count.
The pipeline is YOLO inference over every frame of a video — on CPU, one run
pins a core for minutes. A class of twenty students uploading at the end of a
lesson was therefore twenty concurrent YOLO processes.

That is not only this app's problem. The deployment target is a shared VPS that
also runs the organisation's public site, the scheduling dashboard, and four
other applications. The failure mode is not "HoopAI gets slow", it is "the box
stops answering" — and the containers that fall over first are whichever ones
need memory next, not necessarily this one.

So: a fixed worker count (one by default), a short queue, and a hard refusal
when the queue is full. A student who gets "try again in a minute" has had a
bad experience. A student who takes down the school's website has had a worse
one.

The queue is in-process and therefore not durable: a restart loses anything
queued but not started, and those jobs are marked failed on the next boot
rather than sitting at 'pending' forever. Durability would mean Redis or a
database-backed queue, which is a reasonable next step and not one to take
before the app has users.
"""

from __future__ import annotations

import logging
import queue
import subprocess
import sys
import threading
from pathlib import Path

from backend import config
from backend.database import connection

log = logging.getLogger("hoopai.jobs")


class QueueFull(RuntimeError):
    """Raised when the backlog is at capacity; surfaces to the client as 429."""


_queue: "queue.Queue[tuple[str, str, str]]" = queue.Queue(maxsize=config.JOB_QUEUE_SIZE)
_workers: list[threading.Thread] = []
_shutdown = threading.Event()


def _set_status(job_id: str, status: str, **fields: object) -> None:
    assignments = ", ".join(f"{key} = ?" for key in fields)
    sql = f"UPDATE jobs SET status = ?{', ' + assignments if assignments else ''} WHERE id = ?"
    with connection() as conn:
        conn.execute(sql, (status, *fields.values(), job_id))


def _run_pipeline(job_id: str, video_path: str, clips_dir: str) -> None:
    _set_status(job_id, "processing")
    try:
        result = subprocess.run(
            [
                sys.executable,
                "hoopal.py",
                "--input", video_path,
                "--output", clips_dir,
                "--model", str(config.MODEL_PATH),
            ],
            capture_output=True,
            text=True,
            cwd=config.PIPELINE_ROOT,
            timeout=config.JOB_TIMEOUT_SECONDS,
            check=False,
        )

        # The original ignored the exit status entirely and inferred success
        # from the clip count, so a pipeline that crashed on frame 1 was
        # reported to the student as "done, 0 baskets found" — indistinguishable
        # from a video with no baskets in it.
        if result.returncode != 0:
            log.error("job %s: hoopal.py exited %s\n%s", job_id, result.returncode, result.stderr[-4000:])
            _set_status(
                job_id,
                "error",
                error=f"Processing failed (exit {result.returncode}). Ask an instructor to check the logs.",
            )
            return

        clip_count = len(list(Path(clips_dir).glob("*.mp4")))
        _set_status(job_id, "done", basket_count=clip_count, error=None)
        log.info("job %s: done, %d clip(s)", job_id, clip_count)

    except subprocess.TimeoutExpired:
        log.warning("job %s: timed out after %ss", job_id, config.JOB_TIMEOUT_SECONDS)
        _set_status(job_id, "error", error="Processing timed out. Try a shorter video.")
    except Exception:
        # The message stored for the student is deliberately generic: the
        # original wrote `str(e)` into a field it then returned over the API,
        # which leaks absolute host paths and stack detail to anyone who can
        # upload. The detail goes to the log, where an instructor can read it.
        log.exception("job %s: unhandled failure", job_id)
        _set_status(job_id, "error", error="Processing failed unexpectedly.")


def _worker_loop() -> None:
    while not _shutdown.is_set():
        try:
            item = _queue.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            _run_pipeline(*item)
        finally:
            _queue.task_done()


def submit(job_id: str, video_path: str, clips_dir: str) -> None:
    """Queue a job, or raise QueueFull.

    `put_nowait` rather than a blocking `put`: this is called from a request
    handler, and blocking here would hold the HTTP connection open for however
    long the backlog takes — turning a queue-full condition into a pile of
    hung requests, which is the thing the queue exists to prevent.
    """
    try:
        _queue.put_nowait((job_id, video_path, clips_dir))
    except queue.Full as exc:
        raise QueueFull from exc


def start_workers() -> None:
    if _workers:
        return
    _shutdown.clear()
    for n in range(config.JOB_WORKERS):
        thread = threading.Thread(target=_worker_loop, name=f"hoopai-worker-{n}", daemon=True)
        thread.start()
        _workers.append(thread)
    log.info("started %d job worker(s), queue size %d", config.JOB_WORKERS, config.JOB_QUEUE_SIZE)


def stop_workers(timeout: float = 5.0) -> None:
    _shutdown.set()
    for thread in _workers:
        thread.join(timeout=timeout)
    _workers.clear()


def fail_orphaned_jobs() -> None:
    """Resolve jobs left mid-flight by a restart.

    Without this they stay 'pending'/'processing' forever and the student's
    page spins indefinitely — the queue is in-process, so nothing is ever going
    to pick them up again.
    """
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE jobs SET status = 'error', error = ? WHERE status IN ('pending', 'processing')",
            ("Interrupted by a server restart. Please upload again.",),
        )
        if cursor.rowcount:
            log.warning("marked %d interrupted job(s) as failed", cursor.rowcount)


def depth() -> int:
    """Current backlog, for /health."""
    return _queue.qsize()
