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
# 页面卸载时结束会话只能走 sendBeacon/keepalive，二者都无法携带自定义请求头。
# 仅这两条路径允许用 query 参数完成双提交校验——放开到全部写接口会让 CSRF
# token 进入访问日志、浏览器历史与 Referer。
_QUERY_TOKEN_PATHS = frozenset({
    "/api/v1/dialogue/session/end",
    "/api/v1/multi-dialogue/session/end",
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


# 需要 CSRF 与限流覆盖的路径前缀。新增写路由若挂在这些前缀之外，会静默失去
# 保护，因此这里集中定义，供 main.py 的限流中间件复用。
PROTECTED_PATH_PREFIXES = ("/api/", "/admin/")


def is_protected_path(path: str) -> bool:
    return path.startswith(PROTECTED_PATH_PREFIXES)


def _normalized_path(path: str) -> str:
    if len(path) > 1 and path.endswith("/"):
        return path.rstrip("/")
    return path


def is_csrf_exempt(path: str, method: str) -> bool:
    if method.upper() in _SAFE_METHODS:
        return True
    return _normalized_path(path) in _EXEMPT_PATHS


def _allows_query_token(path: str) -> bool:
    """Only page-unload beacon endpoints may carry the token in the query string."""
    return _normalized_path(path) in _QUERY_TOKEN_PATHS


def uses_bearer_auth(request: Request) -> bool:
    authorization = request.headers.get("Authorization", "")
    return authorization.startswith("Bearer ")


def validate_csrf(request: Request) -> JSONResponse | None:
    """Return a 403 response when cookie-session write lacks a valid CSRF pair."""
    if is_csrf_exempt(request.url.path, request.method):
        return None
    if not is_protected_path(request.url.path):
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
    if not header_token and _allows_query_token(request.url.path):
        # sendBeacon/keepalive 请求无法携带自定义头，允许经 query 参数双提交。
        header_token = request.query_params.get("csrf_token") or ""
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
