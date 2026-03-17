"""
main.py — Sprint 5 update.

Middleware registration order matters.
Last registered = first to run on incoming requests.
So: CORS (outermost) → Metrics → Logging (innermost, closest to handler)
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.metrics import MetricsMiddleware
from app.routers import auth, students, library, courses, health, assistant, api_keys, gov
from app.core.context import get_request_id

settings = get_settings()

# Configure logging first — before any logger.info() calls
configure_logging()
logger = get_logger("api.startup")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
University Services API

## Authentication
All endpoints (except /auth/login and /auth/refresh) require a Bearer JWT token.
Government reporting endpoints (/v1/gov/*) require an **X-API-Key** header with `service` role instead.

## Roles
- **student**: own profile, enroll in courses, borrow books
- **faculty**: view students and courses in their department
- **librarian**: manage books and borrowings
- **admin**: full access
- **service**: machine-to-machine (API key only) — gov reporting endpoints

## Observability
- GET /health/live  — liveness probe
- GET /health/ready — readiness probe (checks DB + Redis)
- GET /metrics      — Prometheus-format metrics
    """,
    docs_url="/docs" ,
    redoc_url="/redoc" ,
    openapi_url="/openapi.json" ,
)

# ── Rate Limiter ──────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# ── Middleware Stack (registration order = reverse execution order) ────────────
app.add_middleware(
    CORSMiddleware,
    #allow_origins=settings.ALLOWED_ORIGINS,
    allow_origins=["*"],
    allow_credentials=True,
    #allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    #allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Location"],
)
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestLoggingMiddleware)


# ── Global Exception Handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Logs the REAL exception internally, returns safe message to client.
    request_id in both log and response so support can correlate.
    """
    logger.error(
        "unhandled_exception",
        extra={
            "request_id": get_request_id(),
            "path": str(request.url.path),
            "method": request.method,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        },
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        headers={"X-Request-ID": get_request_id()},
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred. Our team has been notified.",
                "request_id": get_request_id(),
            }
        }
    )


# ── Lifecycle Events ──────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info(
        "application_starting",
        extra={
            "app_name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        }
    )


@app.on_event("shutdown")
async def shutdown():
    from app.services.cache import close_redis
    await close_redis()
    logger.info("application_shutdown")


# ── Routers ───────────────────────────────────────────────────────────────────
API_PREFIX = "/v1"

app.include_router(health.router)                              # no version prefix
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(students.router, prefix=API_PREFIX)
app.include_router(courses.router, prefix=API_PREFIX)
app.include_router(library.router, prefix=API_PREFIX)
app.include_router(library.borrowings_router, prefix=API_PREFIX)
app.include_router(assistant.router, prefix=API_PREFIX)
app.include_router(api_keys.router, prefix=API_PREFIX)         # Sprint 9
app.include_router(gov.router, prefix=API_PREFIX)              # Sprint 9


# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs" if settings.ENVIRONMENT != "production" else "Access via developer portal",
        "health": "/health/ready",
        "metrics": "/metrics",
    }




@app.get("/admin", include_in_schema=False)
async def admin_dashboard():
    """Serve the admin dashboard UI."""
    import os
    dashboard_path = os.path.join(os.path.dirname(__file__), "uni-api-dashboard.html")
    if not os.path.exists(dashboard_path):
        return JSONResponse(
            status_code=404,
            content={"error": "Dashboard file not found. Place uni-api-dashboard.html next to main.py."}
        )
    return FileResponse(dashboard_path, media_type="text/html")


@app.get("/assistant-ui", include_in_schema=False)
async def library_assistant_ui():
    """Serve the library assistant UI."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "library-assistant.html")
    if not os.path.exists(path):
        return JSONResponse(
            status_code=404,
            content={"error": "Library assistant UI not found."}
        )
    return FileResponse(path, media_type="text/html")


@app.get("/redoc-local", include_in_schema=False)
async def redoc_local():
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>University API - ReDoc</title>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
        <style>body {{ margin: 0; padding: 0; }}</style>
    </head>
    <body>
        <redoc spec-url='/openapi.json'></redoc>
        <script src="https://cdn.jsdelivr.net/npm/redoc/bundles/redoc.standalone.js"></script>
    </body>
    </html>
    """)
