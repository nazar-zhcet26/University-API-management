"""
middleware/rate_limit.py
------------------------
Rate limiting using SlowAPI (a FastAPI wrapper around limits library).

Why rate limiting?
Without it, a single bad actor can:
- Hammer your API until your server dies (DoS)
- Brute-force login credentials (10,000 password attempts/second)
- Scrape your entire student database in seconds

We implement TWO layers of rate limiting:
1. Here in FastAPI (this file) — first line of defense
2. In Azure APIM (Sprint 3) — catches traffic before it even hits your app

For login endpoints especially, we use a strict limit (10/minute) because
legitimate users don't need to try logging in more than a few times.

SlowAPI uses a "limiter" object attached to the FastAPI app.
The @limiter.limit() decorator on individual routes sets per-route limits.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, Response
from fastapi.responses import JSONResponse

# get_remote_address extracts the client IP from the request
# In production behind a load balancer or Azure APIM, you'd use
# X-Forwarded-For header instead. We'll configure that in Sprint 3.
limiter = Limiter(key_func=get_remote_address)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """
    Custom handler for when rate limit is exceeded.
    Returns our consistent ErrorResponse format (not SlowAPI's default).
    Also returns the standard Retry-After header so clients know when to retry.
    """
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": f"Too many requests. {exc.detail}",
            }
        },
        headers={"Retry-After": "60"},
    )
