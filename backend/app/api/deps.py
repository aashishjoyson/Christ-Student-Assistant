from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request, status

from app.container import AppContainer


def get_container(request: Request) -> AppContainer:
    return request.app.state.container  # type: ignore[no-any-return]


def require_admin(request: Request, x_admin_key: str | None = Header(default=None)) -> None:
    """Development-only protection for admin routes (X-Admin-Key header). Not production auth."""
    settings = get_container(request).settings
    if not settings.admin_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin routes are disabled. Set ADMIN_API_KEY in .env.")
    expected = settings.admin_api_key.get_secret_value()  # type: ignore[union-attr]
    if not x_admin_key or not hmac.compare_digest(x_admin_key.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid admin key.")
