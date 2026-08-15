"""Double-submit CSRF protection for cookie-authenticated writes."""

from __future__ import annotations

import hmac
import logging
import secrets
from collections.abc import Iterable
from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from memoria.core.config import configs

logger = logging.getLogger(__name__)

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


_LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def _authority_parts(url_value: str):
    """Return (lowercased hostname, effective port) for an Origin/Referer URL."""
    parsed = urlsplit(url_value)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return hostname, port


def _host_parts(host_header: str):
    """Parse the Host header into (lowercased hostname, effective port)."""
    parsed = urlsplit(f"//{host_header}")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return hostname, port


def _same_origin(url_value: str, host_header: str) -> bool:
    """Compare an Origin/Referer URL authority against the request Host header.

    ``localhost``/``127.0.0.1``/``::1`` are treated as one loopback family and
    port differences are ignored, so the Vite dev proxy
    (``http://localhost:5173`` → ``127.0.0.1:8001``) is not treated as an
    attacker-controlled cross-origin request. Non-loopback hosts still require
    exact hostname and port match.
    """
    if not url_value or not host_header:
        return True
    try:
        origin_host, origin_port = _authority_parts(url_value)
        host_name, host_port = _host_parts(host_header)
    except ValueError:
        return False
    if not origin_host or not host_name:
        return True
    if origin_host in _LOOPBACK_HOSTNAMES and host_name in _LOOPBACK_HOSTNAMES:
        return True
    return origin_host == host_name and origin_port == host_port


def _exempt_path_origin_allowed(request: Request) -> bool:
    """Login/register are CSRF-exempt by design; still block cross-origin browsers.

    Missing Origin/Referer is allowed to stay compatible with non-browser clients.
    """
    host_header = request.headers.get("host", "")
    origin = request.headers.get("origin", "")
    if origin and not _same_origin(origin, host_header):
        logger.warning(
            "CSRF 豁免端点收到跨源请求: path=%s origin=%s host=%s",
            request.url.path,
            origin,
            host_header,
        )
        return False
    referer = request.headers.get("referer", "")
    if referer and not _same_origin(referer, host_header):
        logger.warning(
            "CSRF 豁免端点收到跨源 Referer: path=%s referer=%s host=%s",
            request.url.path,
            referer,
            host_header,
        )
        return False
    return True


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
        # 只有显式豁免的登录/注册写端点需要做 Origin/Referer 同源复核；
        # GET 等安全方法不能被当成“豁免端点”拦截，否则 Vite 开发代理的
        # 跨端口请求也会被 403。
        if (
            request.method.upper() not in _SAFE_METHODS
            and not _exempt_path_origin_allowed(request)
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "请求来源不被允许"},
            )
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
