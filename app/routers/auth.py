"""
routers/auth.py
---------------
Authentication endpoints: login and token refresh.

These are the ONLY endpoints without auth protection — they ARE the auth.
Everything else requires the token issued here.

Flow:
1. Client POSTs email + password to /auth/login
2. We verify credentials against the database
3. We issue an access token (short-lived) + refresh token (longer-lived)
4. Client uses access token in Authorization header for all other requests
5. When access token expires, client POSTs refresh token to /auth/refresh
6. We issue a new access token (without re-entering password)

Rate limiting is stricter here:
- Login: 10/minute (prevents brute force)
- Refresh: 30/minute (more generous since no password involved)

In production with Azure AD:
You wouldn't implement this yourself — Azure AD handles login and token
issuance. Your API just validates the token. But understanding this flow
from scratch is essential to know what Azure is doing for you.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import (
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from app.core.config import get_settings
from app.models.models import User
from app.schemas.schemas import LoginRequest, TokenResponse, RefreshRequest
from app.middleware.rate_limit import limiter
from jose import JWTError

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse, status_code=200)
@limiter.limit("10/minute")  # strict — brute force protection
async def login(
    request: Request,  # needed by SlowAPI for rate limiting
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate a user and issue JWT tokens.
    
    Security design decisions:
    
    1. We always return the same error message whether the email doesn't exist
       or the password is wrong. This is intentional — "user not found" vs
       "wrong password" gives an attacker information about which emails are
       registered. Uniform error = no information leakage.
    
    2. We check is_active — suspended students can't log in even with correct credentials.
       This is authorization at the authentication layer.
    
    3. We issue both access AND refresh tokens in one call.
       The access token goes in the response body.
       In a real app, the refresh token would go in an httpOnly cookie
       so JavaScript can't access it. For our API-first system, we return
       it in the body for simplicity — but document this trade-off.
    """
    # Look up user by email
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    # Uniform error — don't reveal whether email exists or password is wrong
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": {
                "code": "INVALID_CREDENTIALS",
                "message": "Invalid email or password."
            }
        },
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not user:
        # Still call verify_password with a dummy hash to prevent timing attacks.
        # If we returned immediately when user doesn't exist, an attacker could
        # tell valid emails from invalid ones by measuring response time.
        verify_password("dummy", "$2b$12$dummyhashtopreventtimingattacks123456789")
        raise credentials_exception

    if not verify_password(body.password, user.hashed_password):
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "ACCOUNT_SUSPENDED",
                    "message": "Your account has been suspended. Contact IT support."
                }
            }
        )

    # Issue tokens
    access_token = create_access_token(subject=user.id, role=user.role)
    refresh_token = create_refresh_token(subject=user.id, role=user.role)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=TokenResponse, status_code=200)
@limiter.limit("30/minute")
async def refresh_token(
    request: Request,
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Issue a new access token using a valid refresh token.
    
    The client calls this when their access token expires (they get a 401).
    Instead of making the user re-enter their password, they use the
    longer-lived refresh token to silently get a new access token.
    
    We still check the database here — unlike access token validation,
    refresh needs to verify the user still exists and is still active.
    This is the one database call in the auth flow, and it only happens
    every 60 minutes (when access tokens expire), not on every request.
    """
    try:
        token_data = decode_refresh_token(body.refresh_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "INVALID_REFRESH_TOKEN",
                    "message": "Refresh token is invalid or expired."
                }
            }
        )

    # Re-check user is still active (they might have been suspended since last login)
    result = await db.execute(select(User).where(User.id == token_data.subject))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "USER_NOT_FOUND_OR_INACTIVE",
                    "message": "Cannot refresh token for this user."
                }
            }
        )

    # Issue new access token (and rotate refresh token — security best practice)
    new_access_token = create_access_token(subject=user.id, role=user.role)
    new_refresh_token = create_refresh_token(subject=user.id, role=user.role)

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
