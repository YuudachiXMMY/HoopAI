"""The access-control tests.

These are the ones to keep green. The app's whole deployment story is "students
get accounts on a public box", and every assertion here is a way that story
went wrong in the first version of the API.
"""

from __future__ import annotations

import io

import pytest

from tests.conftest import auth


# Above config.MIN_UPLOAD_BYTES (1 KiB). The floor exists so a 0-byte file is
# not a free jobs row; these tests are not about that, so they clear it.
def _upload(client, token, name="game.mp4", body=b"\0" * 4096):
    return client.post(
        "/video/upload",
        headers=auth(token),
        files={"file": (name, io.BytesIO(body), "video/mp4")},
    )


# -- The IDOR ------------------------------------------------------------------


def test_a_student_cannot_read_another_students_job(client, make_user):
    """The regression test for the original get_results.

    That handler called get_user_from_token and discarded the result, then
    looked the job up by id alone. Against it, this test fails: student two
    gets a 200 and student one's results.
    """
    _, alice = make_user()
    _, bob = make_user()

    job_id = _upload(client, alice).json()["job_id"]

    stolen = client.get(f"/video/results/{job_id}", headers=auth(bob))
    assert stolen.status_code == 404, (
        "another student's job must not be readable; "
        f"got {stolen.status_code}: {stolen.text}"
    )

    mine = client.get(f"/video/results/{job_id}", headers=auth(alice))
    assert mine.status_code == 200


def test_a_student_cannot_download_another_students_clip(client, make_user, tmp_path):
    _, alice = make_user()
    _, bob = make_user()

    job_id = _upload(client, alice).json()["job_id"]

    from backend import config

    clip = config.HIGHLIGHTS_DIR / job_id / "basket_01.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"clip")

    assert client.get(f"/video/results/{job_id}/clips/basket_01.mp4", headers=auth(bob)).status_code == 404
    assert client.get(f"/video/results/{job_id}/clips/basket_01.mp4", headers=auth(alice)).status_code == 200


def test_job_list_shows_only_your_own(client, make_user):
    _, alice = make_user()
    _, bob = make_user()

    _upload(client, alice)
    _upload(client, alice)
    bob_job = _upload(client, bob).json()["job_id"]

    listed = client.get("/video/jobs", headers=auth(alice)).json()
    assert len(listed) == 2
    assert bob_job not in {job["job_id"] for job in listed}


def test_a_missing_job_and_someone_elses_job_are_indistinguishable(client, make_user):
    """Both 404, so the endpoint cannot be used to test whether an id exists."""
    _, alice = make_user()
    _, bob = make_user()

    real = _upload(client, alice).json()["job_id"]
    fake = "11111111-2222-3333-4444-555555555555"

    not_yours = client.get(f"/video/results/{real}", headers=auth(bob))
    not_real = client.get(f"/video/results/{fake}", headers=auth(bob))

    assert not_yours.status_code == not_real.status_code == 404
    assert not_yours.json() == not_real.json()


# -- Authentication ------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no header"),
        pytest.param({"Authorization": "Bearer not-a-token"}, id="garbage token"),
        pytest.param({"Authorization": "Basic abc"}, id="wrong scheme"),
    ],
)
def test_protected_endpoints_require_a_valid_bearer_token(client, headers):
    for path in ("/video/jobs", "/video/results/anything"):
        assert client.get(path, headers=headers).status_code in (401, 403)


def test_a_token_signed_with_another_key_is_rejected(client, make_user):
    """The reason HOOPAI_SECRET_KEY has no default.

    The published literal that used to live in auth.py is exactly this: a key
    an attacker has. If anything here ever accepts it, every account is open.
    """
    import datetime as dt

    import jwt

    forged = jwt.encode(
        {
            "sub": "1",
            "email": "student1@example.com",
            "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        },
        "hoopai-secret-change-in-production",
        algorithm="HS256",
    )
    assert client.get("/video/jobs", headers=auth(forged)).status_code == 401


def test_an_alg_none_token_is_rejected(client):
    """PyJWT honours the token's own `alg` header unless told not to."""
    import jwt

    forged = jwt.encode({"sub": "1", "exp": 9999999999}, key="", algorithm="none")
    assert client.get("/video/jobs", headers=auth(forged)).status_code == 401


def test_an_expired_token_is_rejected(client, monkeypatch):
    import datetime as dt

    import jwt

    from backend import config

    expired = jwt.encode(
        {"sub": "1", "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)},
        config.SECRET_KEY,
        algorithm="HS256",
    )
    assert client.get("/video/jobs", headers=auth(expired)).status_code == 401
