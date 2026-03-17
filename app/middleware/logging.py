"""
app/middleware/logging.py
-------------------------
Request logging middleware.

Logs every HTTP request and response as a structured JSON event.
This gives you a complete audit trail of everything that happened.

What gets logged per request:
  On request arrival (DEBUG level):
    - method, path, query string, client IP, user agent

  On response (INFO for success, WARNING for 4xx, ERROR for 5xx):
    - Everything from request + status code + duration in milliseconds

Why log both request and response?
  If a request causes your server to crash (unhandled exception),
  you might only get the request log — the response never comes.
  That tells you exactly which request caused the crash.

What NOT to log:
  - Authorization headers (contains tokens)
  - Request/response bodies (may contain sensitive data)
  - Passwords in any form

Duration measurement:
  We record the start time before the request handler runs and
  calculate duration after it completes. This captures the total
  time including your database queries, cache operations, etc.
  This is your API's actual response time from the server's perspective.
"""

import time
import uuid
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.core.context import set_request_id, get_request_id
from app.core.logging import get_logger

logger = get_logger("api.requests")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware that logs every request and response.

    BaseHTTPMiddleware from Starlette is the standard way to add
    middleware to FastAPI. The dispatch method wraps every request.
    """

    # Paths we don't need to log — reduces noise in logs
    SKIP_LOGGING_PATHS = {"/health", "/metrics", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip health checks — they run every 30 seconds and would flood logs
        if request.url.path in self.SKIP_LOGGING_PATHS:
            return await call_next(request)

        # ── Step 1: Set up correlation ID ──────────────────────────────────
        # Use the ID from APIM's global policy if present,
        # otherwise generate a new one
        request_id = (
            request.headers.get("X-Request-ID")
            or str(uuid.uuid4())
        )
        set_request_id(request_id)

        # ── Step 2: Record start time ──────────────────────────────────────
        start_time = time.perf_counter()

        # ── Step 3: Log request arrival ────────────────────────────────────
        logger.debug(
            "request_received",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query) if request.url.query else None,
                "client_ip": self._get_client_ip(request),
                "user_agent": request.headers.get("User-Agent", "unknown")[:200],
            }
        )

        # ── Step 4: Process the request ────────────────────────────────────
        response: Response = await call_next(request)

        # ── Step 5: Calculate duration ─────────────────────────────────────
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # ── Step 6: Attach correlation ID to response ──────────────────────
        # Consumer can include this in support tickets
        response.headers["X-Request-ID"] = request_id

        # ── Step 7: Log response ───────────────────────────────────────────
        log_data = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client_ip": self._get_client_ip(request),
        }

        # Log level based on status code
        if response.status_code >= 500:
            logger.error("request_completed", extra=log_data)
        elif response.status_code >= 400:
            logger.warning("request_completed", extra=log_data)
        else:
            logger.info("request_completed", extra=log_data)

        # ── Step 8: Alert on slow requests ────────────────────────────────
        # Log a warning for requests that exceed our SLO threshold
        # This surfaces in monitoring dashboards without needing a full APM tool
        if duration_ms > 2000:
            logger.warning(
                "slow_request_detected",
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                    "threshold_ms": 2000,
                }
            )

        return response

    def _get_client_ip(self, request: Request) -> str:
        """
        Get the real client IP address.

        Behind Azure APIM or a load balancer, the direct connection IP
        is the gateway IP, not the real client. The real IP is in the
        X-Forwarded-For header. We read that first.

        We only take the FIRST IP in X-Forwarded-For because it's the
        original client. Subsequent IPs are proxies along the way.
        """
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.client.host if request.client else "unknown"
