"""
core/config.py
--------------
Central configuration using Pydantic Settings.

Why Pydantic Settings?
- Reads values from environment variables automatically
- Validates types (if DATABASE_URL is missing, it fails loudly at startup)
- In production you set real env vars; in dev you use a .env file
- Never hardcode secrets in source code — this pattern enforces that

In Azure, you set these as App Service environment variables or
pull them from Azure Key Vault. Same code, different values per environment.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── Application ──────────────────────────────────────────
    APP_NAME: str = "University Services API"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"  # development | staging | production
    DEBUG: bool = False

    # ── Database ─────────────────────────────────────────────
    # asyncpg driver for async SQLAlchemy
    # Format: postgresql+asyncpg://user:password@host:port/dbname
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/university_db"

    # ── JWT / Security ────────────────────────────────────────
    # SECRET_KEY: used to sign JWTs in dev/test (symmetric HS256)
    # In production with Azure AD, you'd use asymmetric RS256 and
    # Azure AD handles key management. We'll cover that in Sprint 3.
    SECRET_KEY: str = "dev-secret-key-change-this-in-production-minimum-32-chars"
    ALGORITHM: str = "HS256"

    # Access token: short-lived (15-60 min). If stolen, expires quickly.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Refresh token: longer-lived. Used ONLY to get a new access token.
    # The client stores this securely (httpOnly cookie, not localStorage).
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # Azure OpenAI (Sprint 7)
    AZURE_OPENAI_ENDPOINT: str = "https://your-resource.openai.azure.com/"
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_API_VERSION: str = "2024-02-01"
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-ada-002"
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = "gpt-4o"

    # ── Rate Limiting ─────────────────────────────────────────
    # Applied per IP address by our SlowAPI middleware
    # In Sprint 3, Azure APIM adds a second layer of rate limiting on top
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_AUTH: str = "10/minute"  # stricter on login endpoints

    # ── CORS ──────────────────────────────────────────────────
    # Which frontend origins are allowed to call this API
    # In production, lock this down to your actual frontend URLs
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
        "https://portal.university.ac.ae",
    ]

    class Config:
        # Reads from a .env file if present (for local development)
        env_file = ".env"
        case_sensitive = True


# lru_cache means this is only instantiated once per process
# Calling get_settings() 100 times returns the same object — no repeated parsing
@lru_cache()
def get_settings() -> Settings:
    return Settings()
