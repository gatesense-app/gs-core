"""
Password hashing (bcrypt) and JWT issue/verify.

Tokens carry the three claims the rest of the system scopes on:
  sub  — user id
  sid  — society id (None for platform_admin)
  role — platform_admin | society_admin | guard | resident
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from backend.config import ACCESS_TOKEN_TTL_MINUTES, JWT_ALGORITHM, JWT_SECRET


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(*, user_id, society_id, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "sid": str(society_id) if society_id else None,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError on invalid/expired tokens."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
