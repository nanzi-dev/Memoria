"""
Security and reliability regression tests for admin auth, avatars, and auth storage.
"""

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _route_dependencies(router, path: str, method: str) -> list[str]:
    for route in router.routes:
        if route.path == path and method in route.methods:
            explicit = [getattr(dep.dependency, "__name__", "") for dep in route.dependencies]
            parameter = [getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies]
            return explicit + parameter
    raise AssertionError(f"route not found: {method} {path}")


def test_admin_and_relationship_write_routes_require_auth_dependency():
    from memoria.api.character_admin import router as character_router
    from memoria.api.event_admin import router as event_router
    from memoria.api.relationship import router as relationship_router
    from memoria.main import app

    assert "require_current_user_id" in _route_dependencies(character_router, "/admin/characters", "POST")
    assert "require_current_user_id" in _route_dependencies(event_router, "/admin/events", "POST")
    assert "require_current_user_id" in _route_dependencies(event_router, "/admin/event-templates", "GET")
    assert "require_current_user_id" in _route_dependencies(event_router, "/admin/event-templates", "POST")
    assert "require_current_user_id" in _route_dependencies(
        event_router,
        "/admin/event-templates/{template_id}",
        "DELETE",
    )
    assert "require_current_user_id" in _route_dependencies(relationship_router, "/relationships", "POST")
    assert "require_current_user_id" in _route_dependencies(
        relationship_router,
        "/relationships/pair/{character_id_a}/{character_id_b}",
        "PUT",
    )
    assert "require_current_user_id" in _route_dependencies(
        relationship_router,
        "/relationships/{character_id_a}/{character_id_b}",
        "DELETE",
    )
    assert "require_current_user_id" in _route_dependencies(
        relationship_router,
        "/relationships/batch",
        "POST",
    )

    for route in app.routes:
        if getattr(route, "path", None) == "/admin/log-level":
            assert "require_current_user_id" in [
                getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies
            ]
            break
    else:
        raise AssertionError("route not found: POST /admin/log-level")


def test_avatar_downloader_rejects_private_ip(monkeypatch):
    from memoria.api import avatar_fetcher

    monkeypatch.setattr(
        avatar_fetcher.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 80))],
    )

    with pytest.raises(HTTPException) as exc_info:
        avatar_fetcher.download_remote_image("http://example.test/avatar.png")

    assert exc_info.value.status_code == 400
    assert "内网" in exc_info.value.detail


def test_avatar_downloader_closes_rejected_response(monkeypatch):
    from memoria.api import avatar_fetcher

    response = SimpleNamespace(
        is_redirect=False,
        headers={"Content-Type": "text/html"},
        close=lambda: setattr(response, "closed", True),
        raise_for_status=lambda: None,
        closed=False,
    )
    monkeypatch.setattr(
        avatar_fetcher.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(avatar_fetcher.requests, "get", lambda *args, **kwargs: response)

    with pytest.raises(HTTPException):
        avatar_fetcher.download_remote_image("https://example.test/avatar")

    assert response.closed is True


def test_user_avatar_url_rejects_url_when_remote_fetch_is_blocked(monkeypatch):
    from memoria.api import user

    saved = {}
    url = "https://gips0.baidu.com/it/u=1370533637,1153028894&fm=3074&app=3074&f=PNG?w=2048&h=2048"

    def fake_download_remote_image(*args, **kwargs):
        raise HTTPException(400, "不允许访问内网或保留地址")

    monkeypatch.setattr(user, "download_remote_image", fake_download_remote_image)
    monkeypatch.setattr(user, "get_current_user_id", lambda token: "usr_1")
    monkeypatch.setattr(
        user.repository,
        "update_user_profile",
        lambda uid, **kwargs: saved.update(user_id=uid, **kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        user.set_avatar_url(
            user.SetAvatarUrlRequest(url=url),
            token="token",
            authorization=None,
            cookie_token=None,
        )

    assert exc_info.value.status_code == 400
    assert "内网" in exc_info.value.detail
    assert saved == {}


def test_legacy_password_login_upgrades_hash_and_persists_token(monkeypatch):
    from memoria.api import user

    password = "abc12345"
    legacy_hash = hashlib.sha256(password.encode()).hexdigest()
    updates = {}
    tokens = {}

    monkeypatch.setattr(user.repository, "get_user_by_username", lambda username: {
        "user_id": "usr_test",
        "username": username,
        "gender": "unknown",
        "password_hash": legacy_hash,
        "avatar_url": None,
    })
    monkeypatch.setattr(user.repository, "update_user_password_hash", lambda uid, hash_value: updates.update(
        user_id=uid,
        password_hash=hash_value,
    ))
    monkeypatch.setattr(user.repository, "create_auth_token", lambda token, uid, expires_at: tokens.update(
        token=token,
        user_id=uid,
        expires_at=expires_at,
    ))

    res = user.login(user.LoginRequest(username="alice", password=password), Response())

    assert res.user.user_id == "usr_test"
    assert updates["password_hash"].startswith("pbkdf2_sha256$")
    assert tokens["token"] == res.token
    assert tokens["user_id"] == "usr_test"


def test_get_current_user_id_reads_persistent_token_before_memory(monkeypatch):
    from memoria.api import user

    user._tokens.clear()
    monkeypatch.setattr(user.repository, "get_user_id_for_auth_token", lambda token: "usr_db")

    assert user.get_current_user_id("token") == "usr_db"


def test_call_light_task_uses_light_client(monkeypatch):
    from memoria.core import llm_client

    called = {}

    class FakeCompletions:
        def create(self, **kwargs):
            called.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="light result"))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm_client, "_get_light_client", lambda: fake_client)
    monkeypatch.setattr(llm_client, "_get_client", lambda: pytest.fail("main client should not be used"))
    monkeypatch.setattr(llm_client, "_retry_call", lambda fn, *args, **kwargs: fn(*args, **kwargs))

    assert llm_client.call_light_task("summarize") == "light result"
    assert called["messages"] == [{"role": "user", "content": "summarize"}]


def test_get_light_client_uses_light_base_url(monkeypatch):
    from memoria.core import llm_client

    created = {}

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            created["base_url"] = base_url
            created["api_key"] = api_key

    monkeypatch.setattr(llm_client.configs, "llm_base_url", "https://main.test/v1")
    monkeypatch.setattr(llm_client.configs, "llm_api_key", SecretStr("main-key"))
    monkeypatch.setattr(llm_client.configs, "llm_light_base_url", "https://light.test/v1")
    monkeypatch.setattr(llm_client.configs, "llm_light_api_key", SecretStr("light-key"))
    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client, "_client", None)
    monkeypatch.setattr(llm_client, "_light_client", None)
    monkeypatch.setattr(llm_client, "_light_client_signature", None)

    client = llm_client._get_light_client()

    assert isinstance(client, FakeOpenAI)
    assert created == {"base_url": "https://light.test/v1", "api_key": "light-key"}


def test_call_light_task_can_ignore_reasoning_content(monkeypatch):
    from memoria.core import llm_client

    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="",
                            reasoning_content="这是一段推理过程，不是最终摘要。",
                        )
                    )
                ]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm_client, "_get_light_client", lambda: fake_client)
    monkeypatch.setattr(llm_client, "_retry_call", lambda fn, *args, **kwargs: fn(*args, **kwargs))

    assert llm_client.call_light_task("summarize", allow_reasoning_fallback=False) == ""
