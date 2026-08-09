from __future__ import annotations

# ---------------------------------------------------------------------------
# C-4 WARNING: IN-PROCESS RATE LIMITING ONLY — NOT SAFE UNDER MULTI-WORKER
# ---------------------------------------------------------------------------
# This module implements rate limiting using a plain in-process dictionary
# (_RATE_LIMIT_BUCKETS). This works correctly only when the application runs
# as a SINGLE uvicorn worker process.
#
# Under multi-worker deployments (uvicorn --workers N, gunicorn, etc.), each
# worker process has its own independent _RATE_LIMIT_BUCKETS dict. An attacker
# can make up to N × max_requests requests per window before any worker sees
# a breach, completely bypassing brute-force and DDoS protections.
#
# HOW TO FIX (production):
#   1. Install: pip install slowapi redis
#   2. Create a Redis-backed limiter:
#        from slowapi import Limiter
#        from slowapi.util import get_remote_address
#        from limits.storage import RedisStorage
#        limiter = Limiter(
#            key_func=get_remote_address,
#            storage_uri=os.getenv("REDIS_URL", "redis://localhost:6379"),
#        )
#   3. Replace calls to enforce_in_memory_rate_limit / check_in_memory_rate_limit
#      with slowapi decorators or dependency wrappers backed by the Redis limiter.
#   4. If Redis is unavailable, enforce single-worker deployment:
#        uvicorn app.main:app --workers 1
# ---------------------------------------------------------------------------

import time
from collections import deque
from threading import Lock

from fastapi import HTTPException
from fastapi.responses import JSONResponse


_RATE_LIMIT_BUCKETS: dict[str, deque[float]] = {}
_RATE_LIMIT_LOCK = Lock()
_MAX_BUCKET_COUNT = 50_000


def _prune_bucket(bucket: deque[float], *, cutoff: float) -> None:
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()


def _prune_empty_buckets(*, cutoff: float) -> None:
    if len(_RATE_LIMIT_BUCKETS) <= _MAX_BUCKET_COUNT:
        return

    for bucket_key in list(_RATE_LIMIT_BUCKETS.keys()):
        bucket = _RATE_LIMIT_BUCKETS.get(bucket_key)
        if bucket is None:
            continue

        _prune_bucket(bucket, cutoff=cutoff)
        if not bucket:
            _RATE_LIMIT_BUCKETS.pop(bucket_key, None)

        if len(_RATE_LIMIT_BUCKETS) <= _MAX_BUCKET_COUNT:
            return


def _rate_limit_json_response(retry_after_seconds: int) -> JSONResponse:
    """Return a standardised 429 JSON response."""
    return JSONResponse(
        status_code=429,
        content={"error": "Too many requests", "retry_after": retry_after_seconds},
        headers={"Retry-After": str(retry_after_seconds)},
    )


def enforce_in_memory_rate_limit(
    *,
    namespace: str,
    key: str,
    max_requests: int,
    window_seconds: int,
) -> None:
    if max_requests <= 0 or window_seconds <= 0:
        return

    normalized_namespace = namespace.strip() or "global"
    normalized_key = key.strip() or "unknown"

    now = time.monotonic()
    cutoff = now - window_seconds
    bucket_key = f"{normalized_namespace}:{normalized_key}"

    with _RATE_LIMIT_LOCK:
        bucket = _RATE_LIMIT_BUCKETS.get(bucket_key)
        if bucket is None:
            bucket = deque()
            _RATE_LIMIT_BUCKETS[bucket_key] = bucket

        _prune_bucket(bucket, cutoff=cutoff)

        if len(bucket) >= max_requests:
            retry_after_seconds = max(1, int(bucket[0] + window_seconds - now))
            raise HTTPException(
                status_code=429,
                detail={"error": "Too many requests", "retry_after": retry_after_seconds},
                headers={"Retry-After": str(retry_after_seconds)},
            )

        bucket.append(now)
        _prune_empty_buckets(cutoff=cutoff)


def check_in_memory_rate_limit(
    *,
    namespace: str,
    key: str,
    max_requests: int,
    window_seconds: int,
) -> int | None:
    """
    Like enforce_in_memory_rate_limit but returns the retry_after seconds if
    limit is exceeded instead of raising, so middleware can return a JSONResponse
    directly. Returns None when the request is allowed.
    """
    if max_requests <= 0 or window_seconds <= 0:
        return None

    normalized_namespace = namespace.strip() or "global"
    normalized_key = key.strip() or "unknown"

    now = time.monotonic()
    cutoff = now - window_seconds
    bucket_key = f"{normalized_namespace}:{normalized_key}"

    with _RATE_LIMIT_LOCK:
        bucket = _RATE_LIMIT_BUCKETS.get(bucket_key)
        if bucket is None:
            bucket = deque()
            _RATE_LIMIT_BUCKETS[bucket_key] = bucket

        _prune_bucket(bucket, cutoff=cutoff)

        if len(bucket) >= max_requests:
            return max(1, int(bucket[0] + window_seconds - now))

        bucket.append(now)
        _prune_empty_buckets(cutoff=cutoff)
        return None
