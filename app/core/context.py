"""
app/core/context.py
-------------------
Request context using Python's contextvars module.

The problem this solves:
  Your logging middleware sets a correlation ID for each request.
  Your router code wants to include that ID in its log lines.
  But the router doesn't have access to the middleware's local variables.

  You could pass the request_id as a parameter to every function, but that
  pollutes every function signature just for logging purposes.

contextvars solves this: it's like a thread-local variable but for
async code (coroutines). Each concurrent request gets its own isolated
copy of the variable. No sharing between requests, no race conditions.

How it works:
  1. Middleware sets request_id_var at the start of each request
  2. Any code running in that request's context can read it with get_request_id()
  3. When the request ends, the context is automatically cleaned up

Usage:
  from app.core.context import get_request_id
  logger.info("enrolling student", extra={"request_id": get_request_id()})
"""

from contextvars import ContextVar
from typing import Optional
import uuid

# The context variable — stores a string (the request ID) or None
# Each concurrent request gets its own isolated copy
request_id_var: ContextVar[Optional[str]] = ContextVar(
    "request_id",
    default=None
)

# Store authenticated user info for the duration of the request
current_user_id_var: ContextVar[Optional[str]] = ContextVar(
    "current_user_id",
    default=None
)

current_user_role_var: ContextVar[Optional[str]] = ContextVar(
    "current_user_role",
    default=None
)


def set_request_id(request_id: str) -> None:
    """Set the correlation ID for the current request context."""
    request_id_var.set(request_id)


def get_request_id() -> str:
    """
    Get the correlation ID for the current request.
    Generates a new one if none has been set (shouldn't happen in normal flow).
    """
    request_id = request_id_var.get()
    if not request_id:
        request_id = str(uuid.uuid4())
        request_id_var.set(request_id)
    return request_id


def set_current_user(user_id: str, role: str) -> None:
    """Store the authenticated user in context after token validation."""
    current_user_id_var.set(user_id)
    current_user_role_var.set(role)


def get_current_user_id() -> Optional[str]:
    return current_user_id_var.get()


def get_current_user_role() -> Optional[str]:
    return current_user_role_var.get()
