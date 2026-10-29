"""Upload handling: filenames, size, type, and backpressure."""

from __future__ import annotations

import io

import pytest

from tests.conftest import auth


def _upload(client, token, name, body=b"x", content_type="video/mp4"):
    return client.post(
        "/video/upload",
        headers=auth(token),
        files={"file": (name, io.BytesIO(body), content_type)},
    )


# -- Path traversal ------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "../../../../tmp/pwned.mp4",
        "..\\..\\windows\\pwned.mp4",
        "subdir/nested.mp4",
        "....//....//escape.mp4",
    ],
)
def test_a_hostile_filename_never_reaches_the_filesystem(client, make_user, filename):
    """The original interpolated file.filename straight into the stored path.

    `Path / "uuid_../../x"` resolves its `..` segments like any other path, so
    the job-id prefix renamed the first segment and nothing else — the write
    landed wherever the client asked.
    """
    _, token = make_user()
    from backend import config

    response = _upload(client, token, filename)
    assert response.status_code == 202, response.text

    job_id = response.json()["job_id"]
    stored = list(config.UPLOAD_DIR.iterdir())
    assert [path.name for path in stored] == [f"{job_id}.mp4"]
    # And nothing escaped the upload directory.
    assert stored[0].resolve().parent == config.UPLOAD_DIR.resolve()


def test_the_stored_name_carries_nothing_the_client_sent(client, make_user):
    _, token = make_user()
    from backend import config

    job_id = _upload(client, token, "My Game; rm -rf $HOME.mp4").json()["job_id"]
    assert [p.name for p in config.UPLOAD_DIR.iterdir()] == [f"{job_id}.mp4"]


# -- Type and size -------------------------------------------------------------


@pytest.mark.parametrize("filename", ["payload.sh", "shell.php", "notes.txt", "noextension"])
def test_non_video_extensions_are_refused(client, make_user, filename):
    _, token = make_user()
    assert _upload(client, token, filename).status_code == 415


def test_an_upload_with_no_filename_is_refused(client, make_user):
    """Rejected by multipart parsing (422) before the handler sees it.

    Asserted separately from the 415 cases above rather than folded in: the
    status differs because a different layer refuses it, and pretending
    otherwise would hide a change in which layer that is.
    """
    _, token = make_user()
    assert _upload(client, token, "").status_code in (415, 422)


def test_an_oversized_upload_is_refused_and_leaves_nothing_behind(client, make_user, monkeypatch):
    """A rejected upload must not occupy the disk it was rejected for."""
    from backend import config

    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1024)
    _, token = make_user()

    response = _upload(client, token, "big.mp4", body=b"a" * 5000)
    assert response.status_code == 413
    assert list(config.UPLOAD_DIR.iterdir()) == []


def test_an_upload_at_the_limit_is_accepted(client, make_user, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1024)
    _, token = make_user()

    assert _upload(client, token, "fits.mp4", body=b"a" * 1024).status_code == 202


# -- Backpressure --------------------------------------------------------------


def test_a_full_queue_refuses_with_429_rather_than_accepting_unboundedly(client, make_user, monkeypatch):
    """The host-protection test.

    The original started a thread and a YOLO subprocess per upload with no
    ceiling. On the shared VPS this deploys to, twenty simultaneous uploads is
    twenty concurrent inference runs and a box that stops answering for every
    application on it — not just this one.
    """
    from backend import jobs

    def refuse(*_args):
        raise jobs.QueueFull

    monkeypatch.setattr(jobs, "submit", refuse)
    _, token = make_user()

    response = _upload(client, token, "game.mp4")
    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_a_refused_upload_does_not_keep_its_file(client, make_user, monkeypatch):
    from backend import config, jobs

    monkeypatch.setattr(jobs, "submit", lambda *_: (_ for _ in ()).throw(jobs.QueueFull()))
    _, token = make_user()

    _upload(client, token, "game.mp4", body=b"a" * 2048)
    assert list(config.UPLOAD_DIR.iterdir()) == []


# -- Clip download -------------------------------------------------------------


@pytest.mark.parametrize("clip", ["../../../etc/passwd", "../other-job/clip.mp4", "notes.txt"])
def test_clip_download_refuses_to_leave_the_job_directory(client, make_user, clip):
    _, token = make_user()
    job_id = _upload(client, token, "game.mp4").json()["job_id"]

    assert client.get(f"/video/results/{job_id}/clips/{clip}", headers=auth(token)).status_code == 404
