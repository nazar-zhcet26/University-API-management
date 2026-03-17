"""
app/routers/api_keys.py
-----------------------
CRUD endpoints for API key management.

All endpoints require admin role — API keys are privileged credentials
and only admins should be able to issue or revoke them.

Import pattern matches your existing routers:
  - Models from app.models.models (single file)
  - Schemas from app.schemas.api_key (Sprint 9 addition)
  - Auth deps from app.dependencies.auth
  - ApiKey model from app.models.api_key (Sprint 9 addition)
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.dependencies.auth import get_current_user, require_role
from app.core.security import TokenData
from app.middleware.api_key_auth import generate_api_key
from app.models.api_key import ApiKey
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyUpdate,
    ApiKeyResponse,
    ApiKeyCreateResponse,
    ApiKeyListResponse,
)

router = APIRouter(prefix="/api-keys", tags=["API Keys"])

# Admin-only shorthand — all endpoints in this router require admin
require_admin = require_role(["admin"])


# ── POST /v1/api-keys ─────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create API key",
    description="Generates a new API key. The raw key is returned exactly once — store it securely.",
)
async def create_api_key(
    body:         ApiKeyCreate,
    db:           AsyncSession = Depends(get_db),
    current_user: TokenData    = Depends(require_admin),
):
    raw_key, key_hash, key_prefix = generate_api_key()

    expires_at = None
    if body.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)

    api_key = ApiKey(
        name       = body.name,
        key_hash   = key_hash,
        key_prefix = key_prefix,
        user_id    = current_user.subject,
        role       = body.role,
        is_active  = True,
        expires_at = expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyCreateResponse(key=raw_key, api_key=api_key)


# ── GET /v1/api-keys ──────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=ApiKeyListResponse,
    summary="List API keys",
    description="Returns all API keys. Never includes key hashes — only prefix and metadata.",
)
async def list_api_keys(
    db:           AsyncSession = Depends(get_db),
    current_user: TokenData    = Depends(require_admin),
):
    result = await db.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))
    keys   = result.scalars().all()

    count_result = await db.execute(select(func.count()).select_from(ApiKey))
    total        = count_result.scalar_one()

    return ApiKeyListResponse(data=list(keys), total=total)


# ── PATCH /v1/api-keys/{key_id} ───────────────────────────────────────────────

@router.patch(
    "/{key_id}",
    response_model=ApiKeyResponse,
    summary="Update API key",
    description="Update name, active status, or expiry. Cannot change role or regenerate hash.",
)
async def update_api_key(
    key_id:       str,
    body:         ApiKeyUpdate,
    db:           AsyncSession = Depends(get_db),
    current_user: TokenData    = Depends(require_admin),
):
    result  = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "API key not found"}},
        )

    if body.name       is not None: api_key.name       = body.name
    if body.is_active  is not None: api_key.is_active  = body.is_active
    if body.expires_at is not None: api_key.expires_at = body.expires_at

    await db.commit()
    await db.refresh(api_key)
    return api_key


# ── DELETE /v1/api-keys/{key_id} ──────────────────────────────────────────────

@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke API key",
    description="Soft-deletes by setting is_active=False. Row kept for audit trail.",
)
async def revoke_api_key(
    key_id:       str,
    db:           AsyncSession = Depends(get_db),
    current_user: TokenData    = Depends(require_admin),
):
    result  = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "API key not found"}},
        )

    api_key.is_active = False
    await db.commit()


# ── POST /v1/api-keys/{key_id}/rotate ────────────────────────────────────────

@router.post(
    "/{key_id}/rotate",
    response_model=ApiKeyCreateResponse,
    summary="Rotate API key",
    description=(
        "Generates a new key and replaces the stored hash atomically. "
        "The old key stops working immediately. Returns the new raw key once."
    ),
)
async def rotate_api_key(
    key_id:       str,
    db:           AsyncSession = Depends(get_db),
    current_user: TokenData    = Depends(require_admin),
):
    result  = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "NOT_FOUND", "message": "API key not found"}},
        )

    if not api_key.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "KEY_REVOKED", "message": "Cannot rotate a revoked key. Create a new one instead."}},
        )

    raw_key, key_hash, key_prefix = generate_api_key()

    # Atomically replace hash — old key is dead the moment this commits
    api_key.key_hash   = key_hash
    api_key.key_prefix = key_prefix
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyCreateResponse(key=raw_key, api_key=api_key)