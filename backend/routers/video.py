"""Video upload, job status, and clip download.

THE AUTHORISATION BUG THIS FILE WAS REWRITTEN TO FIX

`get_results` used to open with:

    get_user_from_token(authorization)

— the return value discarded — and then look the job up by id alone. The call
reads like an authorisation check and is not one: it proves the caller holds
*a* valid token, never that the job belongs to them. Job ids are UUID4 and so
not guessable, but "unguessable identifier" is a speed bump, not an access
control: ids appear in URLs, in screenshots, in the shared-laptop browser
history of a classroom. Any student with any account could read any other
student's results by quoting one.

Every handler below therefore takes `user_id` from `CurrentUser` and puts it in
the WHERE clause. The pattern to preserve: the dependency returns an id and the
query uses it. A handler that calls the dependency and ignores what it returns
is the bug, re-introduced.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from backend import config, jobs
from backend.database import connection
from backend.security import decode_token

log = logging.getLogger("hoopai.video")

router = APIRouter()

# Replaces `authorization: str = Header(...)` plus a manual
# `.replace("Bearer ", "")`. That string replace was not anchored, so a token
# containing the substring anywhere had it stripped out of the middle; the
# scheme was never actually verified either.
_bearer = HTTPBearer(auto_error=True)


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> int:
    try:
        return decode_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


CurrentUser = Annotated[int, Depends(current_user)]


class UploadAccepted(BaseModel):
    job_id: str
    status: str


class JobResult(BaseModel):
    job_id: str
    status: str
    basket_count: int
    clips: list[str]
    error: str | None


def _safe_suffix(filename: str | None) -> str:
    """Return a vetted extension, or reject the upload.

    The original built its path as `UPLOAD_DIR / f"{job_id}_{file.filename}"`
    with the client-supplied name interpolated raw. `Path.__truediv__` does not
    sanitise, and `..` segments resolve, so a filename of
    `../../../../etc/cron.d/x` escaped the upload directory entirely — the
    `{job_id}_` prefix only renames the first segment, it does not anchor the
    rest. The stored name here is the job UUID plus an allow-listed extension;
    nothing the client sent reaches the filesystem.
    """
    suffix = Path(filename or "").suffix.lower()
    if suffix not in config.ALLOWED_VIDEO_EXTENSIONS:
        allowed = ", ".join(sorted(config.ALLOWED_VIDEO_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type. Allowed extensions: {allowed}",
        )
    return suffix


async def _store_upload(upload: UploadFile, destination: Path) -> None:
    """Stream the body to disk, aborting past MAX_UPLOAD_BYTES.

    The original was `content = await file.read()` — the entire upload into
    memory before a single byte hit disk, with no ceiling. A phone video is
    routinely over a gigabyte, and the container has a memory limit; the first
    large upload was an OOM kill of the API for every user at once.

    Content-Length is not consulted: it is client-supplied and a chunked
    request need not send one. Counting what actually arrives is the only
    figure that cannot be lied about.
    """
    written = 0
    try:
        with destination.open("wb") as sink:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        # Literal 413 rather than a `status.` name: Starlette
                        # renamed the constant (REQUEST_ENTITY_TOO_LARGE →
                        # CONTENT_TOO_LARGE) and the requirements pin only a
                        # lower bound, so either name is a version trap.
                        status_code=413,
                        detail=f"Video exceeds the {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                    )
                sink.write(chunk)
    except BaseException:
        # Includes the 413 above. Without this the rejected upload stays on
        # disk, so "too large" becomes a way to fill the volume for free.
        destination.unlink(missing_ok=True)
        raise


@router.post("/upload", response_model=UploadAccepted, status_code=status.HTTP_202_ACCEPTED)
async def upload_video(user_id: CurrentUser, file: UploadFile = File(...)) -> UploadAccepted:
    suffix = _safe_suffix(file.filename)

    job_id = str(uuid.uuid4())
    video_path = config.UPLOAD_DIR / f"{job_id}{suffix}"
    clips_dir = config.HIGHLIGHTS_DIR / job_id

    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    await _store_upload(file, video_path)

    with connection() as conn:
        conn.execute(
            "INSERT INTO jobs (id, user_id, status, video_path, clips_dir) VALUES (?, ?, 'pending', ?, ?)",
            (job_id, user_id, str(video_path), str(clips_dir)),
        )

    try:
        jobs.submit(job_id, str(video_path), str(clips_dir))
    except jobs.QueueFull:
        # Refuse loudly rather than queue without bound. See the header comment
        # in jobs.py for why the bound exists at all.
        with connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'error', error = ? WHERE id = ?",
                ("Server busy — not accepted.", job_id),
            )
        video_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many videos are being processed right now. Please try again in a few minutes.",
            headers={"Retry-After": "120"},
        ) from None

    log.info("job %s queued by user %s", job_id, user_id)
    return UploadAccepted(job_id=job_id, status="pending")


def _load_owned_job(job_id: str, user_id: int):
    """Fetch a job belonging to this user, or 404.

    404 rather than 403 for a job owned by someone else: a 403 would confirm
    the id exists, which is the enumeration oracle the ownership check is here
    to remove.
    """
    with connection() as conn:
        job = conn.execute(
            "SELECT * FROM jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        ).fetchone()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job


@router.get("/results/{job_id}", response_model=JobResult)
def get_results(job_id: str, user_id: CurrentUser) -> JobResult:
    job = _load_owned_job(job_id, user_id)

    clips: list[str] = []
    if job["status"] == "done" and job["clips_dir"]:
        clips = sorted(path.name for path in Path(job["clips_dir"]).glob("*.mp4"))

    return JobResult(
        job_id=job_id,
        status=job["status"],
        basket_count=job["basket_count"],
        clips=clips,
        error=job["error"],
    )


@router.get("/results/{job_id}/clips/{clip_name}")
def download_clip(job_id: str, clip_name: str, user_id: CurrentUser) -> FileResponse:
    """Serve one clip to the student who produced it.

    The original listed clip names and provided no way to fetch them, so the
    obvious next step would have been a static mount over the highlights
    directory — which is every job's output, served to anyone, with no owner
    check. Routing downloads through here keeps the ownership check on the path
    that matters.
    """
    job = _load_owned_job(job_id, user_id)

    # `clip_name` is a path segment from the URL and is treated as hostile:
    # FastAPI does not decode `%2e%2e%2f` into a traversal for a non-path
    # converter, but the resolve-and-compare below is what makes that a
    # property of this handler rather than of the router's current behaviour.
    clips_dir = Path(job["clips_dir"]).resolve()
    target = (clips_dir / clip_name).resolve()
    if not target.is_relative_to(clips_dir) or target.suffix.lower() != ".mp4" or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")

    return FileResponse(target, media_type="video/mp4", filename=target.name)


@router.get("/jobs", response_model=list[JobResult])
def list_jobs(user_id: CurrentUser) -> list[JobResult]:
    """This user's jobs, newest first."""
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (user_id,),
        ).fetchall()

    return [
        JobResult(
            job_id=row["id"],
            status=row["status"],
            basket_count=row["basket_count"],
            clips=[],
            error=row["error"],
        )
        for row in rows
    ]
