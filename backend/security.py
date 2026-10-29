"""Password hashing and token handling.

Split out of auth.py so that video.py can verify a token without importing the
signup/login routes — the old arrangement had both modules declare their own
copy of SECRET_KEY, which is how they were able to drift apart silently.
"""

from __future__ import annotations

import datetime as _dt
import threading

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from backend import config

# Argon2id. The previous scheme was a bare `hashlib.sha256(password)`:
# unsalted, so identical passwords produced identical rows, and fast, so a
# leaked table is a wordlist lookup rather than an attack. There is no
# migration path for those hashes and no need for one — the table is empty.
#
# THE PARAMETERS ARE NOT THE LIBRARY DEFAULTS, AND MUST NOT BE.
#
# argon2-cffi defaults to memory_cost=65536 KiB — 64 MiB of RAM per concurrent
# hash — and parallelism=4. Both signup and login are sync `def`, so Starlette
# runs them in the anyio threadpool, which has 40 slots. 40 × 64 MiB is 2.5 GiB
# against a 2 GiB container limit whose budget torch has already mostly spent.
# Signup needs no authentication and no invite, so ~30 concurrent POSTs is an
# unauthenticated OOM kill of the API, repeatable for as long as the attacker
# cares to, with `restart: unless-stopped` obligingly bringing it back.
#
# These are OWASP's second recommended Argon2id profile (19 MiB, t=2, p=1).
# parallelism=1 is also the right call here specifically: the container has a
# 1.5-CPU limit, so four lanes per hash contend rather than help.
#
# Changing these does not invalidate existing hashes — the parameters are
# encoded in each stored string, so old hashes keep verifying under the
# settings they were created with.
_hasher = PasswordHasher(memory_cost=19456, time_cost=2, parallelism=1)

# Second line of defence, and the one that holds if the parameters above are
# ever raised again. Caps how many hashes can be in flight at once regardless
# of how many threadpool slots Starlette is willing to hand out: peak memory
# is bounded at _MAX_CONCURRENT_HASHES × memory_cost rather than at 40 ×
# memory_cost. Requests past the cap wait rather than fail — a slow login is
# a worse experience, an OOM kill is an outage for every app on the host.
_MAX_CONCURRENT_HASHES = 4
_hash_slots = threading.Semaphore(_MAX_CONCURRENT_HASHES)


def hash_password(password: str) -> str:
    with _hash_slots:
        return _hasher.hash(password)


# A real argon2 hash of a value nobody can supply, used to spend the same time
# on a login for an account that does not exist as on one that does. Computed
# once at import rather than per call so the cost lands at startup.
#
# WHY: argon2 is deliberately slow — tens of milliseconds. Returning 401
# immediately for an unknown email and 401-after-a-hash for a known one makes
# the two distinguishable by response time, which rebuilds the account
# enumeration oracle that the identical error messages were there to remove.
# Over a few samples that difference is trivially measurable across the
# internet.
_DUMMY_HASH = _hasher.hash("this value is never a password")


def waste_time_like_a_real_verify() -> None:
    """Spend one password-verification's worth of CPU and return nothing.

    Called on the "no such account" branch of login. Not in a `try` that
    swallows: if this ever raises, the hasher is broken and the login path
    should fail loudly rather than silently losing the timing equalisation.
    """
    verify_password("this value is never a password ", _DUMMY_HASH)


def verify_password(password: str, stored_hash: str) -> bool:
    """Check a password, returning False rather than raising on any mismatch.

    `needs_rehash` is deliberately not handled here. It would be the right
    thing if there were legacy hashes to upgrade; there are none, and a rehash
    path that is never exercised is a rehash path that is wrong when it finally
    runs.
    """
    try:
        with _hash_slots:
            _hasher.verify(stored_hash, password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_token(user_id: int, email: str) -> str:
    now = _dt.datetime.now(_dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        # Was 7 days. A token that outlives the laptop it was issued on is the
        # difference between "a student lost their phone" and "a student lost
        # their account for a week".
        "exp": now + _dt.timedelta(hours=config.TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> int:
    """Return the user id carried by a valid token.

    Raises jwt.InvalidTokenError (or a subclass) for anything else. Note the
    explicit single-entry `algorithms` list: without it PyJWT would honour the
    token's own `alg` header, and `alg: none` is a token anyone can write.
    """
    payload = jwt.decode(
        token,
        config.SECRET_KEY,
        algorithms=[config.JWT_ALGORITHM],
        options={"require": ["exp", "sub"]},
    )
    return int(payload["sub"])
