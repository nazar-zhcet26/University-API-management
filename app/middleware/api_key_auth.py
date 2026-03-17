"""
app/middleware/api_key_auth.py
------------------------------
FastAPI dependency for X-API-Key authentication.

This is NOT a Starlette middleware class (like logging.py / metrics.py).
It's a FastAPI dependency function — it runs only on routes that declare it,
not on every single request globally. That's the right model for auth.

Why a dependency and not a global middleware?
  - Global middleware runs on /health, /docs, /metrics — we don't want auth there.
  - A dependency is opt-in per route, or injected via a router-level dependency
    that covers a whole group of routes at once.
  - It integrates cleanly with FastAPI's existing Depends() chain, so RBAC
    works identically whether the caller used JWT or an API key.

The combined dependency get_current_user_flexible() tries JWT first, then
falls back to X-API-Key. This means routes that currently use get_current_user
can be switched to get_current_user_flexible and will transparently support
both auth methods — no route-level changes needed.

Security properties:
  - The raw key is NEVER stored. Only SHA-256(key) hits the database.
  - Even if someone reads your entire api_keys table they get hashes — useless
    without the original key.
  - The key_prefix column (first 12 chars) is stored plaintext solely so
    admins can identify keys in the dashboard without seeing the secret.
"""

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import decode_access_token, TokenData
from app.models.api_key import ApiKey


# ── helpers ───────────────────────────────────────────────────────────────────

def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.

    Returns (raw_key, key_hash, key_prefix).

    raw_key    — returned to the caller once, never stored.
    key_hash   — SHA-256 hex digest, stored in DB.
    key_prefix — first 12 chars of raw_key, stored for display only.

    Format:  uak_<64 hex chars>
    Example: uak_3f8a2c1b9e4d...
    """
    raw        = "uak_" + secrets.token_hex(32)
    key_hash   = hashlib.sha256(raw.encode()).hexdigest()
    key_prefix = raw[:12]
    return raw, key_hash, key_prefix


def hash_key(raw_key: str) -> str:
    """Hash an incoming key for DB lookup. Same algorithm as generate_api_key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


# ── core dependency ───────────────────────────────────────────────────────────

async def get_api_key_user(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> TokenData:
    """
    Validate an X-API-Key header and return a TokenData object.

    Raises 401 if:
      - Header is missing
      - Key hash not found in DB
      - Key is inactive (revoked)
      - Key is expired

    On success, returns a TokenData with the key's role injected — from
    this point the RBAC system is completely auth-method-agnostic.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"code": "INVALID_API_KEY", "message": "Invalid or missing API key"}},
        headers={"WWW-Authenticate": "ApiKey"},
    )

    if not x_api_key:
        raise credentials_exception

    key_hash = hash_key(x_api_key)

    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash)
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise credentials_exception

    if not api_key.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "API_KEY_REVOKED", "message": "This API key has been revoked"}},
        )

    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "API_KEY_EXPIRED", "message": "This API key has expired"}},
        )

    # Inject the key's role into TokenData so downstream RBAC works
    # identically to JWT auth — the route handler never needs to know
    # which auth method was used.
    return TokenData(subject=api_key.user_id, role=api_key.role, token_type="api_key")

# ── combined dependency ───────────────────────────────────────────────────────

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user_flexible(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> TokenData:
    """
    Accepts EITHER a JWT Bearer token OR an X-API-Key header.

    Try order:
      1. Bearer token  (existing users, dashboard, Swagger UI)
      2. X-API-Key     (machine-to-machine, MuleSoft, MOEHE)

    If both are provided, Bearer takes precedence.
    If neither is provided, raises 401.

    Use this on routes that should accept both auth methods.
    Keep get_current_user (JWT only) on routes that should never
    be accessible via API key (e.g. /auth/refresh).
    """
    from jose import JWTError

    # Try JWT first
    if credentials:
        try:
            return decode_access_token(credentials.credentials)
        except (JWTError, HTTPException):
            pass  # fall through to API key

    # Try API key
    if x_api_key:
        return await get_api_key_user(x_api_key=x_api_key, db=db)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"code": "NOT_AUTHENTICATED", "message": "Authentication required"}},
        headers={"WWW-Authenticate": "Bearer"},
    )