"""Password hashing and token handling.

Split out of auth.py so that video.py can verify a token without importing the
signup/login routes — the old arrangement had both modules declare their own
copy of SECRET_KEY, which is how they were able to drift apart silently.
"""

from __future__ import annotations

import datetime as _dt

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from backend import config

# Argon2id at the library's defaults, which track the OWASP guidance. The
# previous scheme was a bare `hashlib.sha256(password)`: unsalted, so identical
# passwords produced identical rows, and fast, so a leaked table is a
# wordlist lookup rather than an attack. There is no migration path for those
# hashes and no need for one — the table is empty.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Check a password, returning False rather than raising on any mismatch.

    `needs_rehash` is deliberately not handled here. It would be the right
    thing if there were legacy hashes to upgrade; there are none, and a rehash
    path that is never exercised is a rehash path that is wrong when it finally
    runs.
    """
    try:
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
