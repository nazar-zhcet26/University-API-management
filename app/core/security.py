"""
core/security.py
----------------
Everything related to JWT creation, validation, and password hashing.

This is the CORE of Sprint 2. Read every comment carefully.

Key concepts implemented here:
1. Password hashing with bcrypt (never store plain passwords)
2. JWT creation — building the token payload with claims
3. JWT decoding — verifying signature and extracting claims
4. Refresh token pattern — short-lived access + longer-lived refresh

How JWT verification works (important to understand):
- We sign tokens with SECRET_KEY using HS256 (symmetric — same key signs and verifies)
- In production with Azure AD, tokens are signed with Azure's private RSA key
  and you verify using Azure's public key (fetched from their JWKS endpoint)
- Either way, the verification logic here is the same pattern
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import get_settings

settings = get_settings()

# ── Password Hashing ──────────────────────────────────────────────────────────
# bcrypt is the industry standard for password hashing.
# It's slow BY DESIGN — makes brute-force attacks impractical.
# Never use MD5 or SHA256 for passwords — those are fast hashing algorithms
# designed for data integrity, not security.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """
    Hash a plain text password. Call this when creating or updating a user.
    The result is stored in the database — never the plain password.
    
    bcrypt automatically:
    - Generates a random salt (so same password → different hash each time)
    - Includes the salt in the output string (so you don't store it separately)
    """
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Check if a plain password matches a stored hash.
    Used during login — compare what the user typed against what's in the DB.
    """
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT Token Creation ────────────────────────────────────────────────────────

def create_access_token(
    subject: str,           # user ID — becomes the "sub" claim
    role: str,              # user role — custom claim for RBAC
    extra_claims: Optional[dict] = None,  # any additional data to embed
) -> str:
    """
    Create a short-lived JWT access token.
    
    The token payload (claims) includes:
    - sub: the user's ID (standard claim — "subject")
    - role: their role for RBAC checks
    - iat: issued-at timestamp (standard claim)
    - exp: expiry timestamp (standard claim)
    - type: "access" — so we can reject refresh tokens used as access tokens
    
    The token is SIGNED but NOT ENCRYPTED.
    Anyone can decode the payload (it's Base64). 
    But they cannot MODIFY it without invalidating the signature.
    Never put sensitive data (passwords, SSNs) in a JWT payload.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": expire,
        "type": "access",
    }

    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str, role: str) -> str:
    """
    Create a longer-lived refresh token.
    
    This token is ONLY valid for getting a new access token.
    It should be stored in an httpOnly cookie (not accessible to JavaScript),
    not in localStorage.
    
    The "type": "refresh" claim means our access token validator will reject
    this token if someone tries to use it as an access token.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": expire,
        "type": "refresh",
    }

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


# ── JWT Token Validation ──────────────────────────────────────────────────────

class TokenData:
    """
    Structured representation of the decoded JWT payload.
    Returned by decode_token so the rest of the app works with
    typed data rather than raw dictionaries.
    """
    def __init__(self, subject: str, role: str, token_type: str):
        self.subject = subject  # user ID
        self.role = role
        self.token_type = token_type


def decode_access_token(token: str) -> TokenData:
    """
    Decode and validate a JWT access token.
    
    This does three things:
    1. Verifies the signature (was this token issued by us?)
    2. Checks expiry (is it still valid?)
    3. Checks token type (is this actually an access token, not a refresh token?)
    
    Raises JWTError if any check fails.
    The dependency layer catches this and returns 401.
    
    Performance note: this is pure CPU work — no database calls.
    That's the power of JWTs. At 1000 req/sec, you never hit the DB just for auth.
    """
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
        # jose automatically validates exp — raises ExpiredSignatureError if expired
    )

    subject: str = payload.get("sub")
    role: str = payload.get("role")
    token_type: str = payload.get("type")

    if not subject or not role:
        raise JWTError("Token missing required claims")

    if token_type != "access":
        raise JWTError("Invalid token type — expected access token")

    return TokenData(subject=subject, role=role, token_type=token_type)


def decode_refresh_token(token: str) -> TokenData:
    """
    Decode and validate a refresh token.
    Used only at the /auth/refresh endpoint.
    """
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )

    subject: str = payload.get("sub")
    role: str = payload.get("role")
    token_type: str = payload.get("type")

    if token_type != "refresh":
        raise JWTError("Invalid token type — expected refresh token")

    return TokenData(subject=subject, role=role, token_type=token_type)
