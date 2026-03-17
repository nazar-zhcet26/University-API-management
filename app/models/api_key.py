"""
app/models/api_key.py
---------------------
SQLAlchemy ORM model for the api_keys table.

Follows the exact same conventions as models.py:
  - String(36) primary key (not UUID type) — matches your existing tables
  - generate_uuid() for default ID generation
  - DateTime(timezone=True) for timestamps
  - func.now() for server-side defaults
"""

from datetime import datetime
from sqlalchemy import String, Boolean, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.models import generate_uuid


class ApiKey(Base):
    __tablename__ = "api_keys"

    id:         Mapped[str]           = mapped_column(String(36),  primary_key=True, default=generate_uuid)
    name:       Mapped[str]           = mapped_column(String(255), nullable=False)
    key_hash:   Mapped[str]           = mapped_column(String(64),  nullable=False, unique=True, index=True)
    key_prefix: Mapped[str]           = mapped_column(String(12),  nullable=False)
    user_id:    Mapped[str]           = mapped_column(String(36),  ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role:       Mapped[str]           = mapped_column(String(50),  nullable=False, default="service")
    is_active:  Mapped[bool]          = mapped_column(Boolean(),   nullable=False, default=True)
    expires_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationship back to the owning user
    owner: Mapped["User"] = relationship("User", back_populates="api_keys")