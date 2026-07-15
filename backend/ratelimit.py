"""
Per-society rate limiting for the endpoints that spend money.

POST /sessions and POST /sessions/{id}/reply each fan out into real Claude
calls, so an accidental retry loop (or one noisy society) can burn the API
budget and starve every other tenant. Limits are keyed by society_id — taken
from the JWT, never the client — so one tenant can't exhaust another's budget.

Token bucket: `capacity` requests may burst, refilling at `capacity / window`
per second. Bursts are normal at a gate (a delivery wave at 7pm) and the bucket
absorbs them while still bounding the sustained rate.

Scope: in-process. That is honest for a single backend instance, which is how
this deploys today. Behind multiple replicas each process would allow the limit,
so this becomes per-instance — move the buckets to Redis before scaling out.
"""

import threading
import time

from fastapi import Depends, HTTPException, status

from backend.config import RATE_LIMIT_REPLIES, RATE_LIMIT_SESSIONS, RATE_LIMIT_WINDOW_SECONDS
from backend.deps import CurrentUser, get_current_user


class TokenBucket:
    def __init__(self, capacity: int, window_seconds: float):
        self.capacity = float(capacity)
        self.refill_per_second = capacity / window_seconds if window_seconds else 0.0
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_seen)
        self._lock = threading.Lock()

    def take(self, key: str) -> tuple[bool, int]:
        """Consume a token. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill_per_second)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return True, 0
            self._buckets[key] = (tokens, now)
            # Seconds until one whole token is back.
            need = (1.0 - tokens) / self.refill_per_second if self.refill_per_second else 60.0
            return False, max(1, int(need + 0.999))

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


_session_bucket = TokenBucket(RATE_LIMIT_SESSIONS, RATE_LIMIT_WINDOW_SECONDS)
_reply_bucket = TokenBucket(RATE_LIMIT_REPLIES, RATE_LIMIT_WINDOW_SECONDS)


def _limiter(bucket: TokenBucket, what: str):
    def _dep(user: CurrentUser = Depends(get_current_user)) -> None:
        # platform_admin has no society; key on the user instead so the bucket
        # never collapses every tenant onto a single shared key.
        key = user.society_id or f"user:{user.user_id}"
        allowed, retry_after = bucket.take(key)
        if not allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Too many {what} for this society. Retry in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )

    return _dep


limit_sessions = _limiter(_session_bucket, "visitor entries")
limit_replies = _limiter(_reply_bucket, "replies")


def reset_all() -> None:
    """Test helper — drop all buckets so cases don't leak into each other."""
    _session_bucket.reset()
    _reply_bucket.reset()
