from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Optional

from fastapi import HTTPException, Request, status

from app.auth import try_decode_token
from app.config import settings


@dataclass
class RateLimitRule:
    limit: int
    window_seconds: int
    scope: str


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def enforce(self, key: str, rule: RateLimitRule) -> None:
        now = time.time()
        with self._lock:
            bucket = self._buckets[f"{rule.scope}:{key}"]
            while bucket and bucket[0] <= now - rule.window_seconds:
                bucket.popleft()
            if len(bucket) >= rule.limit:
                retry_after = max(1, int(rule.window_seconds - (now - bucket[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please slow down and try again shortly.",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)


rate_limiter = RateLimiter()


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _get_user_identifier(request: Request) -> Optional[str]:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    decoded = try_decode_token(authorization.split(" ", 1)[1].strip())
    if decoded is None:
        return None
    user_id, _role = decoded
    return str(user_id)


def enforce_rate_limit(request: Request) -> None:
    path = request.url.path
    ip_address = _get_client_ip(request)
    user_id = _get_user_identifier(request)

    if path == "/health":
        return

    if path == "/auth/login":
        rate_limiter.enforce(ip_address, RateLimitRule(settings.login_rate_limit_ip, settings.rate_limit_window_seconds, "login-ip"))
        return

    ip_limit = settings.rate_limit_ip_authenticated if user_id else settings.rate_limit_ip_public
    rate_limiter.enforce(ip_address, RateLimitRule(ip_limit, settings.rate_limit_window_seconds, "ip"))

    if user_id:
        rate_limiter.enforce(user_id, RateLimitRule(settings.rate_limit_user_authenticated, settings.rate_limit_window_seconds, "user"))


def enforce_login_identity_rate_limit(identity: str) -> None:
    rate_limiter.enforce(identity.lower(), RateLimitRule(settings.login_rate_limit_user, settings.rate_limit_window_seconds, "login-user"))
