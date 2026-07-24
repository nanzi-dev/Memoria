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


