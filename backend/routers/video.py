import uuid
import threading
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Header
import jwt
from backend.database import get_connection

router = APIRouter()

SECRET_KEY = "hoopai-secret-change-in-production"
UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
HIGHLIGHTS_DIR = Path(__file__).parent.parent / "highlights"


def get_user_from_token(authorization: str):
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["user_id"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def run_pipeline(job_id: str, video_path: str, clips_dir: str):
    import subprocess
    import sys

    conn = get_connection()
    conn.execute("UPDATE jobs SET status = 'processing' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    try:
        result = subprocess.run(
            [sys.executable, "hoopal.py", "--input", video_path, "--output", clips_dir],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Count clips produced
        clips = list(Path(clips_dir).glob("*.mp4"))
        basket_count = len(clips)

        conn = get_connection()
        conn.execute(
            "UPDATE jobs SET status = 'done', basket_count = ? WHERE id = ?",
            (basket_count, job_id),
        )
        conn.commit()
        conn.close()

    except Exception as e:
        conn = get_connection()
        conn.execute(
            "UPDATE jobs SET status = 'error', error = ? WHERE id = ?",
            (str(e), job_id),
        )
        conn.commit()
        conn.close()


@router.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    authorization: str = Header(...),
):
    user_id = get_user_from_token(authorization)

    job_id = str(uuid.uuid4())
    video_path = UPLOAD_DIR / f"{job_id}_{file.filename}"
    clips_dir = HIGHLIGHTS_DIR / job_id

    UPLOAD_DIR.mkdir(exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    with open(video_path, "wb") as f:
        content = await file.read()
        f.write(content)

    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (id, user_id, status, video_path, clips_dir) VALUES (?, ?, 'pending', ?, ?)",
        (job_id, user_id, str(video_path), str(clips_dir)),
    )
    conn.commit()
    conn.close()

    thread = threading.Thread(target=run_pipeline, args=(job_id, str(video_path), str(clips_dir)))
    thread.daemon = True
    thread.start()

    return {"job_id": job_id, "status": "pending"}


@router.get("/results/{job_id}")
def get_results(job_id: str, authorization: str = Header(...)):
    get_user_from_token(authorization)

    conn = get_connection()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    clips = []
    if job["status"] == "done":
        clips_path = Path(job["clips_dir"])
        clips = [f.name for f in clips_path.glob("*.mp4")]

    return {
        "job_id": job_id,
        "status": job["status"],
        "basket_count": job["basket_count"],
        "clips": clips,
        "error": job["error"],
    }
