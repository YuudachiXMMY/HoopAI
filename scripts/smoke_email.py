"""scripts/smoke_email.py
Post-deploy check that outbound email works end to end, with an exit code.

Run it after any deploy that touches auth or mail configuration. It answers the
question that took an ssh session and a log grep to answer last time — and that
was answered too late, after three real signups had silently received nothing:

    1. is the key present and accepted by Resend,
    2. is `config.EMAIL_FROM`'s domain a verified sender, and
    3. does a message actually reach `delivered`.

Each step is checked separately because they fail for different reasons and the
first two are invisible from the application side: auth.py logs a send failure
and returns, so signup answers 201 either way.

Run it inside the API container, which is where the app's environment lives:

    ssh hoopai "ops shell api"      # then, at the prompt:
    python scripts/smoke_email.py

It imports `backend.config` rather than reading the environment itself, so that
it cannot drift from what the running API believes — including HOOPAI_SECRET_KEY,
which config requires at import and which this check has no other use for.

Exit code is 0 only on a delivered message. Nothing here prints the API key.
"""

from __future__ import annotations

import sys
import time

import httpx

from backend import config

_API = "https://api.resend.com"

# Resend's own sink address. Mail sent here traverses the real send path and is
# really delivered, to nobody — which is what lets this run on every deploy
# without mailing a person or creating a throwaway account in the production
# database to receive it. `bounced@` and `complained@` simulate the other
# outcomes, should this ever need to assert them.
_SINK = "delivered@resend.dev"

# Events after which Resend will report nothing further; anything else means
# the message is still in flight and polling should continue.
_TERMINAL = {"delivered", "bounced", "complained", "failed", "canceled"}

_DELIVERY_TIMEOUT_SECONDS = 60
_POLL_INTERVAL_SECONDS = 3


def sender_domain(address: str) -> str:
    """The domain of an address that may or may not carry a display name.

    `config.EMAIL_FROM` is written in the form Resend shows to recipients
    (`HoopAI <noreply@example.com>`), while the domains endpoint lists bare
    domains, so the two cannot be compared without this. Splitting on `<`
    first matters: `rsplit("@")` alone would survive a display name containing
    an `@`, but return the wrong thing for one containing `>`.
    """
    if "<" in address:
        address = address.split("<", 1)[1].split(">", 1)[0]
    return address.rsplit("@", 1)[-1].strip().lower()


def main() -> int:
    if not config.EMAIL_ENABLED:
        print("  Email  : DISABLED (HOOPAI_RESEND_API_KEY unset) — nothing to check")
        print("           If this is production, that is the bug: set the key.")
        return 1

    headers = {"Authorization": f"Bearer {config.RESEND_API_KEY}"}
    expected_domain = sender_domain(config.EMAIL_FROM)
    print(f"  From   : {config.EMAIL_FROM}")

    # 1. Is the key accepted? A read-only call, so a bad key costs nothing.
    #    Response bodies are safe to print: Resend echoes the request, never
    #    the bearer token.
    try:
        response = httpx.get(f"{_API}/domains", headers=headers, timeout=15.0)
    except httpx.HTTPError as exc:
        print(f"  Key    : UNREACHABLE ({exc.__class__.__name__}: {exc})")
        return 1
    if response.status_code != 200:
        print(f"  Key    : REJECTED (HTTP {response.status_code}) {response.text[:200]}")
        return 1
    print("  Key    : ok")

    # 2. Is the sender domain verified? Checked here rather than left to the
    #    send below because the failure is a 403 whose message says nothing
    #    about DNS, and because this reports *which* domains are registered —
    #    the usual cause is a key belonging to a different Resend account.
    domains = {entry.get("name"): entry.get("status") for entry in response.json().get("data") or []}
    status = domains.get(expected_domain)
    if status != "verified":
        print(f"  Domain : {expected_domain} is {status or 'not registered'}, need 'verified'")
        print(f"           registered on this key: {sorted(domains) or 'none'}")
        return 1
    print(f"  Domain : {expected_domain} verified")

    # 3. Send for real.
    try:
        response = httpx.post(
            f"{_API}/emails",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "from": config.EMAIL_FROM,
                "to": [_SINK],
                "subject": "HoopAI post-deploy smoke check",
                "html": "<p>Automated deploy check. No action needed.</p>",
            },
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        print(f"  Send   : UNREACHABLE ({exc.__class__.__name__}: {exc})")
        return 1
    if response.status_code >= 400:
        print(f"  Send   : FAILED (HTTP {response.status_code}) {response.text[:200]}")
        return 1
    email_id = response.json().get("id")
    print(f"  Send   : accepted, id={email_id}")

    # 4. Accepted is not delivered — the send above returns an id as soon as
    #    the message is queued. Poll for a terminal event so that a key which
    #    can queue mail but not deliver it still fails this check.
    deadline = time.monotonic() + _DELIVERY_TIMEOUT_SECONDS
    last_event = None
    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL_SECONDS)
        response = httpx.get(f"{_API}/emails/{email_id}", headers=headers, timeout=15.0)
        if response.status_code != 200:
            print(f"  Status : unreadable (HTTP {response.status_code}) {response.text[:200]}")
            return 1
        last_event = response.json().get("last_event")
        if last_event in _TERMINAL:
            break

    if last_event != "delivered":
        reported = last_event or f"no terminal event within {_DELIVERY_TIMEOUT_SECONDS}s"
        print(f"  Status : {reported}, expected 'delivered'")
        return 1

    print("  Status : delivered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
