"""
dependencies/auth.py
--------------------
FastAPI dependency injection for authentication and authorization.

This is where RBAC lives in practice.

How FastAPI Dependency Injection works:
    async def my_endpoint(current_user = Depends(get_current_user)):
        ...

FastAPI calls get_current_user BEFORE executing my_endpoint.
If get_current_user raises an HTTPException, the endpoint never runs.
This is how we enforce auth without repeating the same code in every endpoint.

The three levels of protection we implement:

1. get_current_user → just validates the JWT, returns user data
   Use for: any endpoint that requires login but has no role restriction

2. require_role(["admin", "librarian"]) → validates JWT + checks role
   Use for: endpoints restricted to specific roles

3. require_self_or_admin → validates JWT + checks ownership OR admin role
   Use for: endpoints like GET /students/{id} where students can see
   their own profile but not others', while admins see everyone

This is the fix for OWASP #1 (BOLA) and #5 (Broken Function Level Auth)
that we discussed in the theory section.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from app.core.security import decode_access_token, TokenData
from app.schemas.schemas import UserRole

# HTTPBearer extracts the JWT from the Authorization: Bearer <token> header
# auto_error=False means we handle the missing token case ourselves
# (so we can return our consistent ErrorResponse format instead of FastAPI's default)
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenData:
    """
    Base authentication dependency.
    
    Extracts and validates the JWT from the Authorization header.
    Returns the decoded token data (user ID + role).
    
    Raises 401 if:
    - No Authorization header present
    - Token is malformed
    - Token signature is invalid
    - Token is expired
    - Token is a refresh token (wrong type)
    
    This runs in microseconds — pure CPU, no database call.
    That's the JWT advantage.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "MISSING_TOKEN",
                    "message": "Authentication required. Include a Bearer token in the Authorization header."
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        token_data = decode_access_token(credentials.credentials)
        return token_data
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "INVALID_TOKEN",
                    "message": f"Token validation failed: {str(e)}"
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_role(allowed_roles: list[str]):
    """
    Role-based authorization dependency factory.
    
    Usage:
        @router.delete("/students/{id}")
        async def delete_student(
            student_id: str,
            current_user: TokenData = Depends(require_role(["admin"]))
        ):
    
    Why a factory (function that returns a function)?
    Because we need to pass parameters (the allowed roles) to a dependency.
    FastAPI dependencies can't take parameters directly, so we wrap them.
    
    This is the fix for OWASP #5 — every sensitive endpoint explicitly
    declares which roles can access it.
    """
    async def _check_role(
        current_user: TokenData = Depends(get_current_user)
    ) -> TokenData:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "INSUFFICIENT_PERMISSIONS",
                        "message": f"This action requires one of the following roles: {', '.join(allowed_roles)}"
                    }
                }
            )
        return current_user

    return _check_role


def require_self_or_role(id_param: str, allowed_roles: list[str]):
    """
    Ownership + role dependency factory.
    
    Allows access if:
    - The authenticated user IS the resource owner (their subject == resource ID), OR
    - The authenticated user has one of the allowed_roles
    
    This is the fix for OWASP #1 (BOLA — Broken Object Level Authorization).
    
    Example: GET /students/{student_id}
    - Student stu_10042 can see their own profile (subject matches student_id)
    - Student stu_10042 CANNOT see stu_99999 (different subject, not admin)
    - Admin can see any profile (role check passes)
    
    Usage:
        @router.get("/students/{student_id}")
        async def get_student(
            student_id: str,
            current_user: TokenData = Depends(require_self_or_role("student_id", ["admin", "faculty"]))
        ):
    
    Note: id_param is the name of the path parameter to check against.
    FastAPI's Request object lets us access path params dynamically.
    """
    from fastapi import Request

    async def _check_self_or_role(
        request: Request,
        current_user: TokenData = Depends(get_current_user)
    ) -> TokenData:
        resource_id = request.path_params.get(id_param)

        # Allow if: user is accessing their own resource
        if current_user.subject == resource_id:
            return current_user

        # Allow if: user has a privileged role
        if current_user.role in allowed_roles:
            return current_user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "ACCESS_DENIED",
                    "message": "You can only access your own resources unless you have elevated permissions."
                }
            }
        )

    return _check_self_or_role


# ── Convenience shortcuts ──────────────────────────────────────────────────────
# Pre-built dependencies for common role combinations.
# These make the router code cleaner — one import, descriptive name.

require_admin = require_role(["admin"])
require_admin_or_librarian = require_role(["admin", "librarian"])
require_admin_or_faculty = require_role(["admin", "faculty"])
require_any_authenticated = get_current_user  # just needs a valid token
