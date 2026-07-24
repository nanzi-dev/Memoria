"""Double-submit CSRF protection for cookie-authenticated writes."""

from __future__ import annotations

import hmac
import secrets
from typing import Iterable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from memoria.core.config import configs

CSRF_COOKIE_NAME = "memoria-csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # align with auth cookie

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
# Auth bootstrap endpoints authenticate via body credentials, not cookie session.
_EXEMPT_PATHS = frozenset({
    "/api/v1/user/login",
    "/api/v1/user/register",
})


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, token: str | None = None) -> str:
    """Write a readable (non-HttpOnly) CSRF cookie for double-submit checks."""
    value = token or generate_csrf_token()
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=value,
        max_age=CSRF_COOKIE_MAX_AGE,
        httponly=False,
        samesite="lax",
        secure=configs.auth_cookie_secure,
        path="/",
    )
    return value


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


def ensure_csrf_cookie(request: Request, response: Response) -> str:
    """Reuse existing CSRF cookie when present; otherwise mint a new one."""
    existing = request.cookies.get(CSRF_COOKIE_NAME)
    if existing:
        # Re-set so clients that lost the cookie attribute still receive it.
        return set_csrf_cookie(response, existing)
    return set_csrf_cookie(response)


def _normalized_path(path: str) -> str:
    if len(path) > 1 and path.endswith("/"):
        return path.rstrip("/")
    return path


def is_csrf_exempt(path: str, method: str) -> bool:
    if method.upper() in _SAFE_METHODS:
        return True
    return _normalized_path(path) in _EXEMPT_PATHS


def uses_bearer_auth(request: Request) -> bool:
    authorization = request.headers.get("Authorization", "")
    return authorization.startswith("Bearer ")


def validate_csrf(request: Request) -> JSONResponse | None:
    """Return a 403 response when cookie-session write lacks a valid CSRF pair."""
    if is_csrf_exempt(request.url.path, request.method):
        return None
    if not request.url.path.startswith("/api/"):
        return None
    # Bearer-token clients are not cookie sessions; CSRF does not apply.
    if uses_bearer_auth(request):
        return None
    # No auth cookie => no cookie-session CSRF surface for this request.
    auth_cookie = request.cookies.get("memoria-token")
    if not auth_cookie:
        return None

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME) or ""
    header_token = request.headers.get(CSRF_HEADER_NAME) or ""
    if (
        not cookie_token
        or not header_token
        or not hmac.compare_digest(cookie_token, header_token)
    ):
        return JSONResponse(
            status_code=403,
            content={"detail": "CSRF 校验失败"},
        )
    return None


def csrf_exempt_paths() -> Iterable[str]:
    return tuple(sorted(_EXEMPT_PATHS))
