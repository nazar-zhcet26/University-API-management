"""
app/schemas/api_key.py
----------------------
Pydantic schemas for API key request/response shapes.

Follows the same XBase / XCreate / XUpdate / XResponse pattern as schemas.py.
String IDs to match your existing schema — no UUID type here.

Key rule: ApiKeyResponse NEVER includes key_hash.
ApiKeyCreateResponse is the ONLY schema that carries the raw key,
and only because it's the one-time creation/rotation response.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


# ── Request schemas ───────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    name:            str            = Field(..., min_length=1, max_length=255)
    role:            str            = Field(default="service")
    expires_in_days: Optional[int]  = Field(default=365, ge=1, le=3650)


class ApiKeyUpdate(BaseModel):
    name:       Optional[str]      = None
    is_active:  Optional[bool]     = None
    expires_at: Optional[datetime] = None


# ── Response schemas ──────────────────────────────────────────────────────────

class ApiKeyResponse(BaseModel):
    """Safe representation — never includes key_hash or the raw key."""
    model_config = ConfigDict(from_attributes=True)

    id:         str
    name:       str
    key_prefix: str
    role:       str
    is_active:  bool
    expires_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ApiKeyCreateResponse(BaseModel):
    """
    Returned ONLY on POST /v1/api-keys and POST /v1/api-keys/{id}/rotate.
    Includes the raw key — caller must copy it now, it's unrecoverable after this.
    """
    key:     str            = Field(..., description="Raw API key — store this securely, shown only once")
    api_key: ApiKeyResponse


class ApiKeyListResponse(BaseModel):
    data:  list[ApiKeyResponse]
    total: int