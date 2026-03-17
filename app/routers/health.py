"""
app/routers/health.py
---------------------
Health check endpoints.

Two endpoints, two different purposes:

GET /health/live — Liveness probe
  Is the process alive?
  If this fails: restart the container immediately.
  Should NEVER fail unless the process is completely dead.
  No dependency checks here — just return 200.

GET /health/ready — Readiness probe
  Is the process ready to serve traffic?
  If this fails: stop sending traffic here (but don't restart).
  Checks all dependencies: database, Redis.
  Returns 503 if any critical dependency is down.

GET /health — Simple combined check (for backwards compatibility)
  Used by Azure APIM's backend health check.

Why separate liveness and readiness?
  Classic scenario: your database goes down for 30 seconds.
  - Without readiness: all requests hit your API, all fail with 500
  - With readiness: load balancer sees 503 readiness, stops routing here,
    database comes back, readiness returns 200, traffic resumes
  Your API never returns 500 to users — just a brief service unavailable

Kubernetes and Azure Container Apps use these paths by convention:
  livenessProbe: GET /health/live
  readinessProbe: GET /health/ready

Azure APIM uses /health for its backend health check.
"""

import time
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from app.core.database import AsyncSessionLocal
from app.core.config import get_settings
from app.services.cache import get_redis
from app.middleware.metrics import metrics

settings = get_settings()
router = APIRouter(tags=["Health"])

# Track startup time for uptime reporting
START_TIME = time.time()


@router.get("/health/live")
async def liveness():
    """
    Liveness probe — is the process running?
    Always returns 200 unless the process is dead (in which case
    this endpoint would be unreachable anyway).
    """
    return {
        "status": "alive",
        "version": settings.APP_VERSION,
        "uptime_seconds": round(time.time() - START_TIME),
    }


@router.get("/health/ready")
async def readiness():
    """
    Readiness probe — are all dependencies healthy?

    Checks:
    1. PostgreSQL: can we connect and run a simple query?
    2. Redis: can we connect and ping?

    Returns 200 if all healthy, 503 if any dependency is down.
    The response body tells you WHICH dependency failed.

    503 Service Unavailable is the correct code here:
      - 500 = our fault, something broke
      - 503 = we're temporarily unavailable, try again later
    """
    checks = {}
    all_healthy = True

    # ── Check PostgreSQL ───────────────────────────────────────────────────
    try:
        start = time.perf_counter()
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_latency = round((time.perf_counter() - start) * 1000, 2)
        checks["database"] = {
            "status": "healthy",
            "latency_ms": db_latency,
        }
    except Exception as e:
        checks["database"] = {
            "status": "unhealthy",
            "error": str(e),
        }
        all_healthy = False

    # ── Check Redis ────────────────────────────────────────────────────────
    try:
        start = time.perf_counter()
        redis = await get_redis()
        await redis.ping()
        redis_latency = round((time.perf_counter() - start) * 1000, 2)
        checks["cache"] = {
            "status": "healthy",
            "latency_ms": redis_latency,
        }
    except Exception as e:
        checks["cache"] = {
            "status": "unhealthy",
            "error": str(e),
        }
        # Redis being down is degraded, not completely broken
        # (we fail gracefully in the cache service)
        # So we don't set all_healthy = False for Redis
        checks["cache"]["degraded"] = True

    response_body = {
        "status": "ready" if all_healthy else "not_ready",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "uptime_seconds": round(time.time() - START_TIME),
        "checks": checks,
    }

    status_code = 200 if all_healthy else 503
    return JSONResponse(content=response_body, status_code=status_code)


@router.get("/health")
async def health():
    """
    Simple health check — used by Azure APIM backend health probe.
    Just checks the process is alive and returns version info.
    """
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }


@router.get("/metrics")
async def get_metrics():
    """
    Prometheus-format metrics endpoint.

    Prometheus (or Azure Monitor) scrapes this endpoint every 15 seconds
    and stores the time-series data for dashboards and alerts.

    In production with Azure Application Insights, you'd use the
    opencensus-ext-azure package instead of this manual implementation.
    But understanding what metrics ARE is more important than which
    library generates them.

    Example response:
      http_requests_total{method="GET",path="/v1/courses"} 4231
      http_errors_total{method="POST",path="/v1/enrollments"} 3
      http_request_duration_ms{method="GET",path="/v1/courses",quantile="0.95"} 234.5
    """
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        content=metrics.to_prometheus(),
        media_type="text/plain; version=0.0.4"
    )
