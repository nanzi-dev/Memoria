"""CSRF double-submit protection for cookie sessions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import Response
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_login_sets_csrf_cookie_readable():
    from memoria.api import user
    from memoria.db import repository

    username = "csrf_login_user"
    password = "Secret123"
    if not repository.get_user_by_username(username):
        repository.create_user("usr_csrf1", username, user._hash_password(password), "unknown")

    response = Response()
    user.login(user.LoginRequest(username=username, password=password), response)
    set_cookie = response.headers.getlist("set-cookie") if hasattr(response.headers, "getlist") else [response.headers.get("set-cookie", "")]
    joined = "\n".join(set_cookie)
    assert "memoria-csrf=" in joined
    # CSRF cookie must be JS-readable (no HttpOnly on that cookie line).
    csrf_lines = [line for line in joined.split("\n") if "memoria-csrf=" in line]
    assert csrf_lines
    assert "HttpOnly" not in csrf_lines[0] or "memoria-csrf=" in csrf_lines[0] and "HttpOnly" not in csrf_lines[0].split("memoria-csrf=")[1].split(",")[0]


def test_validate_csrf_rejects_cookie_write_without_header():
    from memoria.core.csrf import CSRF_COOKIE_NAME, validate_csrf

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/user/profile",
        "raw_path": b"/api/v1/user/profile",
        "query_string": b"",
        "headers": [
            (b"cookie", b"memoria-token=abc; memoria-csrf=tok123"),
        ],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    request = Request(scope)
    blocked = validate_csrf(request)
    assert blocked is not None
    assert blocked.status_code == 403


def test_validate_csrf_accepts_matching_double_submit():
    from memoria.core.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, validate_csrf

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/user/profile",
        "raw_path": b"/api/v1/user/profile",
        "query_string": b"",
        "headers": [
            (b"cookie", b"memoria-token=abc; memoria-csrf=tok123"),
            (b"x-csrf-token", b"tok123"),
        ],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    request = Request(scope)
    assert validate_csrf(request) is None


def test_validate_csrf_skips_bearer_auth():
    from memoria.core.csrf import validate_csrf

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/user/profile",
        "raw_path": b"/api/v1/user/profile",
        "query_string": b"",
        "headers": [
            (b"authorization", b"Bearer abc"),
            (b"cookie", b"memoria-token=abc"),
        ],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    request = Request(scope)
    assert validate_csrf(request) is None


def test_validate_csrf_skips_login_endpoint():
    from memoria.core.csrf import validate_csrf

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/user/login",
        "raw_path": b"/api/v1/user/login",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }
    request = Request(scope)
    assert validate_csrf(request) is None




def _csrf_scope(path: str, query_string: bytes = b"", headers=None):
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query_string,
        "headers": headers or [(b"cookie", b"memoria-token=abc; memoria-csrf=tok123")],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
    }


@pytest.mark.parametrize(
    "path",
    ["/api/v1/dialogue/session/end", "/api/v1/multi-dialogue/session/end"],
)
def test_validate_csrf_accepts_query_token_on_beacon_endpoints(path):
    """sendBeacon/keepalive 无法带自定义头，这两条路径允许 query 参数双提交。"""
    from memoria.core.csrf import validate_csrf

    request = Request(_csrf_scope(path, query_string=b"csrf_token=tok123"))
    assert validate_csrf(request) is None


def test_validate_csrf_rejects_query_token_on_other_endpoints():
    """query 回退不得外溢到其它写接口，否则 token 会进日志/历史/Referer。"""
    from memoria.core.csrf import validate_csrf

    request = Request(
        _csrf_scope("/api/v1/user/profile", query_string=b"csrf_token=tok123")
    )
    blocked = validate_csrf(request)
    assert blocked is not None
    assert blocked.status_code == 403


def test_validate_csrf_rejects_mismatched_query_token_on_beacon_endpoint():
    from memoria.core.csrf import validate_csrf

    request = Request(
        _csrf_scope("/api/v1/dialogue/session/end", query_string=b"csrf_token=wrong")
    )
    blocked = validate_csrf(request)
    assert blocked is not None
    assert blocked.status_code == 403


def test_admin_prefix_is_csrf_protected():
    """/admin/ 下的写路由不在 /api/ 前缀内，同样必须走 CSRF 校验。"""
    from memoria.core.csrf import validate_csrf

    request = Request(_csrf_scope("/admin/log-level"))
    blocked = validate_csrf(request)
    assert blocked is not None
    assert blocked.status_code == 403


def test_health_endpoints_stay_unprotected():
    from memoria.core.csrf import is_protected_path

    assert is_protected_path("/api/v1/user/profile")
    assert is_protected_path("/admin/log-level")
    assert not is_protected_path("/health")
    assert not is_protected_path("/ready")
