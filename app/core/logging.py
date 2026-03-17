"""
app/core/logging.py
-------------------
Structured logging configuration.

Why structured (JSON) logging?
  Plain text logs are for humans reading a terminal.
  JSON logs are for machines — Azure Application Insights, Datadog,
  Grafana Loki, and Splunk can all ingest, index, and query JSON logs.

  With JSON logs you can:
  - Filter: show me all logs where status_code >= 500
  - Correlate: show me all logs with request_id = "a3f9b2-..."
  - Aggregate: what's the average duration_ms for /v1/courses in the last hour?
  - Alert: notify me when error_rate > 5% over 5 minutes

  You can't do any of that with "ERROR: Something went wrong at 14:32:01"

The logger we configure here is used by:
  - Our request logging middleware (every HTTP request/response)
  - Application code (business events worth logging)
  - Error handlers (unhandled exceptions)

Usage anywhere in the app:
  from app.core.logging import get_logger
  logger = get_logger(__name__)
  logger.info("student_enrolled", course_id="crs_5010", student_id="stu_10042")
"""

import logging
import json
import sys
from datetime import datetime, timezone
from typing import Any
from app.core.config import get_settings

settings = get_settings()


class JSONFormatter(logging.Formatter):
    """
    Custom log formatter that outputs JSON instead of plain text.

    Standard formatter output:
      2026-03-11 09:03:42,123 - INFO - Student enrolled in course

    Our JSON formatter output:
      {"timestamp": "2026-03-11T09:03:42Z", "level": "INFO",
       "message": "Student enrolled in course", "logger": "app.routers.courses",
       "environment": "production", "course_id": "crs_5010"}

    The extra fields (course_id in the example above) come from
    passing keyword arguments to the logger:
      logger.info("Student enrolled in course", extra={"course_id": "crs_5010"})
    """

    # Fields we always include in every log line
    ALWAYS_INCLUDE = {
        "timestamp", "level", "message", "logger", "environment"
    }

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "environment": settings.ENVIRONMENT,
        }

        # Include any extra fields passed via extra={} or as direct attributes
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            } and not key.startswith("_"):
                log_data[key] = value

        # Include exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


def configure_logging():
    """
    Configure the root logger for the application.
    Call this once at startup in main.py.

    In development: human-readable format (easier to read in terminal)
    In production: JSON format (machine-readable for log aggregators)
    """
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    # Remove any existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # Console handler — always present
    handler = logging.StreamHandler(sys.stdout)

    if settings.ENVIRONMENT == "development":
        # Readable format for local development
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%H:%M:%S"
        ))
    else:
        # JSON format for staging and production
        handler.setFormatter(JSONFormatter())

    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Reduce noise from third-party libraries
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DEBUG else logging.WARNING
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger for a module.

    Usage:
        logger = get_logger(__name__)
        logger.info("Something happened", extra={"user_id": "stu_10042"})

    The name should be __name__ so log lines show which module they came from.
    """
    return logging.getLogger(name)
