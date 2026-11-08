"""Whether outbound email is on must be visible without reading the source.

Three real signups received no verification mail because the only evidence was
one WARNING per signup in a log nobody was grepping. The fix is not better
logging of the failure — the failure was logged — it is that the *mode* is
reported somewhere a person looks anyway: once per restart in the startup log,
and on /health. These tests cover both, in both states.

`config.EMAIL_ENABLED` is monkeypatched rather than set through the
environment: the settings are read once at import, so by the time a test runs,
a change to os.environ would be asserting against a value nothing re-reads.
"""

from __future__ import annotations

import logging

import pytest


@pytest.fixture
def email_on(monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "EMAIL_ENABLED", True)
    monkeypatch.setattr(config, "EMAIL_FROM", "HoopAI <noreply@example.test>")


@pytest.fixture
def email_off(monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "EMAIL_ENABLED", False)


# -- /health ------------------------------------------------------------------


def test_health_reports_email_configured(client, email_on):
    body = client.get("/health").json()
    assert body["email"] == "configured"


def test_health_reports_email_disabled(client, email_off):
    body = client.get("/health").json()
    assert body["email"] == "disabled"


def test_disabled_email_is_still_a_healthy_api(client, email_off):
    """An API with no mail provider works; it must not fail its healthcheck.

    Docker restarts the container on a failing healthcheck, so reporting this
    as unhealthy would turn a missing optional setting into a restart loop —
    and kill whatever pipeline job was mid-flight each time round.
    """
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_never_returns_the_key(client, email_on, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "RESEND_API_KEY", "re_" + "s" * 20)
    assert "s" * 20 not in client.get("/health").text


# -- The startup line ---------------------------------------------------------


def test_startup_states_that_email_is_enabled(email_on, caplog):
    from backend.main import log_email_mode

    with caplog.at_level(logging.INFO, logger="hoopai"):
        log_email_mode()

    assert "outbound email: ENABLED" in caplog.text
    # The sender is part of the line because the other way this breaks is a
    # key that works against the wrong account, which sends as a domain nobody
    # expected.
    assert "noreply@example.test" in caplog.text


def test_startup_warns_when_email_is_disabled(email_off, caplog):
    """WARNING, not INFO.

    On a laptop this is routine, but the level is set for the case that
    matters: a production log being skimmed for problems, where an INFO line
    is scenery.
    """
    from backend.main import log_email_mode

    with caplog.at_level(logging.INFO, logger="hoopai"):
        log_email_mode()

    assert "outbound email: DISABLED" in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    # It must say how to make this fatal, since the reader of this line in a
    # production log is exactly the person who wants that.
    assert "HOOPAI_REQUIRE_EMAIL" in caplog.text


def test_the_startup_line_never_contains_the_key(email_on, caplog, monkeypatch):
    from backend import config
    from backend.main import log_email_mode

    monkeypatch.setattr(config, "RESEND_API_KEY", "re_" + "s" * 20)
    with caplog.at_level(logging.INFO, logger="hoopai"):
        log_email_mode()

    assert "s" * 20 not in caplog.text


# -- The smoke check's one piece of parsing -----------------------------------
#
# Everything else in scripts/smoke_email.py is network calls against Resend and
# is exercised by running it. This is the part that can be wrong in silence:
# a domain mismatch here would compare the right key against the wrong domain
# and report a verified sender as unregistered, or worse, the reverse.


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("HoopAI <noreply@hoopai.ithacateens.com>", "hoopai.ithacateens.com"),
        ("noreply@hoopai.ithacateens.com", "hoopai.ithacateens.com"),
        ("  HoopAI  <NoReply@HoopAI.Example.COM>  ", "hoopai.example.com"),
        # A display name containing an @ — the reason the `<` split comes first.
        ("a@b <noreply@example.test>", "example.test"),
    ],
)
def test_sender_domain(address, expected):
    from scripts.smoke_email import sender_domain

    assert sender_domain(address) == expected


# -- The smoke check's exit code ----------------------------------------------
#
# The whole value of the script is that a deploy can branch on `$?`, so the
# exit code is the thing to test. These drive main() against a stubbed Resend
# rather than the real one: the four stages have to be exercised in their
# failing shapes, and three of those cannot be produced on demand against a
# live account.
#
# The stage-4 polling loop is the reason these exist at all. It is the only
# part with control flow worth getting wrong, and "accepted" is exactly what a
# broken sender returns — so a check that stopped at stage 3 would pass while
# no mail arrived, which is the bug this script was written for.

_SENT_ID = "01a1bbaf-dead-beef-cafe-000000000000"


class _StubResend:
    """Minimal stand-in for the three Resend endpoints the script calls.

    `events` is the sequence `last_event` returns on successive polls, so a
    test can hand back "sent" twice before "delivered" and prove the loop
    actually waits rather than reading the first answer and believing it.
    """

    def __init__(self, *, domains=(("hoopai.example.test", "verified"),), send_status=200, events=("delivered",)):
        self.domains = domains
        self.send_status = send_status
        self.events = list(events)
        self.polls = 0

    def get(self, url, **_):
        if url.endswith("/domains"):
            data = [{"name": name, "status": status} for name, status in self.domains]
            return _StubResponse(200, {"data": data})
        self.polls += 1
        event = self.events[min(self.polls - 1, len(self.events) - 1)]
        return _StubResponse(200, {"last_event": event})

    def post(self, _url, **_kwargs):
        return _StubResponse(self.send_status, {"id": _SENT_ID})


class _StubResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


@pytest.fixture
def smoke(monkeypatch, email_on):
    """The script module, with its clock and its HTTP client replaced."""
    from scripts import smoke_email

    monkeypatch.setattr(smoke_email.config, "RESEND_API_KEY", "re_" + "s" * 20)
    monkeypatch.setattr(smoke_email.config, "EMAIL_FROM", "HoopAI <noreply@hoopai.example.test>")
    monkeypatch.setattr(smoke_email.time, "sleep", lambda _: None)

    def _install(stub):
        monkeypatch.setattr(smoke_email.httpx, "get", stub.get)
        monkeypatch.setattr(smoke_email.httpx, "post", stub.post)
        return smoke_email

    return _install


def test_a_delivered_message_exits_zero(smoke):
    assert smoke(_StubResend()).main() == 0


def test_it_waits_for_delivery_rather_than_trusting_acceptance(smoke):
    """"Accepted" only means queued; the id comes back before any send."""
    stub = _StubResend(events=("sent", "sent", "delivered"))
    assert smoke(stub).main() == 0
    assert stub.polls == 3


def test_a_bounce_exits_nonzero(smoke):
    assert smoke(_StubResend(events=("bounced",))).main() == 1


def test_an_unverified_sender_domain_exits_nonzero(smoke):
    """The 403-at-send-time case, caught one stage earlier and named."""
    stub = _StubResend(domains=(("hoopai.example.test", "pending"),))
    assert smoke(stub).main() == 1


def test_a_key_for_the_wrong_account_exits_nonzero(smoke):
    """A valid key whose account does not hold our domain at all."""
    stub = _StubResend(domains=(("someone-else.example", "verified"),))
    assert smoke(stub).main() == 1


def test_a_rejected_send_exits_nonzero(smoke):
    assert smoke(_StubResend(send_status=422)).main() == 1


def test_a_message_that_never_resolves_exits_nonzero(smoke, monkeypatch):
    """Stuck in flight is a failure, not a pass. Otherwise a deploy check that
    times out reports success."""
    from scripts import smoke_email

    monkeypatch.setattr(smoke_email, "_DELIVERY_TIMEOUT_SECONDS", 1)
    assert smoke(_StubResend(events=("sent",))).main() == 1


def test_no_key_exits_nonzero(monkeypatch, email_off):
    from scripts import smoke_email

    monkeypatch.setattr(smoke_email.config, "EMAIL_ENABLED", False)
    assert smoke_email.main() == 1
