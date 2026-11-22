from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies import require_admin, require_user
from app.core.security import AuthenticatedUser

router = APIRouter(prefix="/auth", tags=["Authentication Verification"])


@router.get("/me", response_model=dict[str, Any])
async def get_my_profile(
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Returns profile of authenticated user with USER role."""
    return {
        "sub": user.id,
        "roles": user.roles,
        "email": user.email,
        "username": user.username,
    }


@router.get("/admin", response_model=dict[str, Any])
async def get_admin_dashboard(
    admin: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """Admin-only endpoint requiring ADMIN role."""
    return {
        "message": "Admin access granted",
        "admin_id": admin.id,
        "roles": admin.roles,
    }
