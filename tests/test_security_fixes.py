"""
Security and reliability regression tests for admin auth, avatars, and auth storage.
"""

import hashlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import BackgroundTasks, HTTPException, Response
from PIL import Image
from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _route_dependencies(router, path: str, method: str) -> list[str]:
    for route in router.routes:
        if route.path == path and method in route.methods:
            explicit = [getattr(dep.dependency, "__name__", "") for dep in route.dependencies]
            parameter = [getattr(dep.call, "__name__", "") for dep in route.dependant.dependencies]
            return explicit + parameter
    raise AssertionError(f"route not found: {method} {path}")


def test_admin_and_relationship_write_routes_require_expected_auth_dependency():
    from memoria.api.character_admin import router as character_router
    from memoria.api.developer import router as developer_router
    from memoria.api.event_admin import router as event_router
    from memoria.api.relationship import router as relationship_router
    from memoria.main import app

    assert "require_current_user_id" in _route_dependencies(character_router, "/admin/characters", "POST")
    assert "require_current_user_id" in _route_dependencies(event_router, "/admin/events", "POST")
    assert "require_current_user_id" in _route_dependencies(event_router, "/admin/event-templates", "GET")
    assert "require_admin_user_id" in _route_dependencies(event_router, "/admin/event-templates", "POST")
    assert "require_admin_user_id" in _route_dependencies(
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
    assert "require_admin_user_id" in _route_dependencies(
        developer_router,
        "/developer/performance",
        "GET",
    )
    assert "require_admin_user_id" in _route_dependencies(
        developer_router,
        "/developer/performance/reset",
        "POST",
    )

    for route in app.routes:
        if getattr(route, "path", None) == "/admin/log-level":
            assert "require_admin_user_id" in [
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

    peer_socket = SimpleNamespace(getpeername=lambda: ("93.184.216.34", 443))
    response = SimpleNamespace(
        is_redirect=False,
        headers={"Content-Type": "text/html"},
        close=lambda: setattr(response, "closed", True),
        raise_for_status=lambda: None,
        raw=SimpleNamespace(_connection=SimpleNamespace(sock=peer_socket)),
        closed=False,
    )
    sessions = []

    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.closed = False
            sessions.append(self)

        def get(self, *args, **kwargs):
            return response

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        avatar_fetcher.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (avatar_fetcher.socket.AF_INET, avatar_fetcher.socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443))
        ],
    )
    monkeypatch.setattr(avatar_fetcher.requests, "Session", FakeSession)

    with pytest.raises(HTTPException):
        avatar_fetcher.download_remote_image("https://example.test/avatar")

    assert response.closed is True
    assert sessions[0].trust_env is False
    assert sessions[0].closed is True


def test_avatar_downloader_rejects_private_connected_peer(monkeypatch):
    from memoria.api import avatar_fetcher

    peer_socket = SimpleNamespace(getpeername=lambda: ("127.0.0.1", 443))
    response = SimpleNamespace(
        raw=SimpleNamespace(_connection=SimpleNamespace(sock=peer_socket)),
        close=lambda: setattr(response, "closed", True),
        closed=False,
    )

    class FakeSession:
        trust_env = True

        def get(self, *args, **kwargs):
            return response

        def close(self):
            pass

    monkeypatch.setattr(
        avatar_fetcher.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (avatar_fetcher.socket.AF_INET, avatar_fetcher.socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443))
        ],
    )
    monkeypatch.setattr(avatar_fetcher.requests, "Session", FakeSession)

    with pytest.raises(HTTPException) as exc_info:
        avatar_fetcher.download_remote_image("https://example.test/avatar")

    assert exc_info.value.status_code == 400
    assert "内网" in exc_info.value.detail
    assert response.closed is True


def test_user_avatar_url_rejects_url_when_remote_fetch_is_blocked(monkeypatch):
    from memoria.api import user

    saved = {}
    url = "https://gips0.baidu.com/it/u=1370533637,1153028894&fm=3074&app=3074&f=PNG?w=2048&h=2048"

    def fake_download_remote_image(*args, **kwargs):
        raise HTTPException(400, "不允许访问内网或保留地址")

    monkeypatch.setattr(user, "download_remote_image", fake_download_remote_image)
    monkeypatch.setattr(
        user.repository,
        "update_user_profile",
        lambda uid, **kwargs: saved.update(user_id=uid, **kwargs),
    )

    with pytest.raises(HTTPException) as exc_info:
        user.set_avatar_url(
            user.SetAvatarUrlRequest(url=url),
            uid="usr_1",
        )

    assert exc_info.value.status_code == 400
    assert "内网" in exc_info.value.detail
    assert saved == {}


def test_user_avatar_rejects_bytes_that_do_not_match_declared_image_mime():
    from memoria.api import user

    with pytest.raises(HTTPException) as exc_info:
        user._avatar_data_url(b"not an image", "image/png")

    assert exc_info.value.status_code == 400
    assert "无效" in exc_info.value.detail


def test_user_avatar_rejects_image_over_pixel_limit():
    from memoria.api import user

    source = io.BytesIO()
    Image.new("1", (4001, 4001)).save(source, format="PNG")

    with pytest.raises(HTTPException) as exc_info:
        user._avatar_data_url(source.getvalue(), "image/png")

    assert exc_info.value.status_code == 400
    assert "像素" in exc_info.value.detail


def test_avatar_decompression_bomb_is_reported_as_validation_error(monkeypatch):
    from memoria.api import avatar_image

    monkeypatch.setattr(
        avatar_image.Image,
        "open",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            Image.DecompressionBombError("declared dimensions are unsafe")
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        avatar_image.avatar_data_url(b"image bytes")

    assert exc_info.value.status_code == 400
    assert "像素" in exc_info.value.detail


@pytest.mark.asyncio
async def test_character_avatar_upload_rejects_invalid_image_bytes(monkeypatch):
    from memoria.api import character_admin

    saved = {}
    monkeypatch.setattr(
        character_admin.repository,
        "get_character_card_from_db",
        lambda *args, **kwargs: {"character_id": "npc-1"},
    )
    monkeypatch.setattr(
        character_admin.repository,
        "update_character_avatar",
        lambda *args, **kwargs: saved.update(called=True),
    )
    upload = SimpleNamespace(
        filename="avatar.png",
        content_type="image/png",
        read=lambda size: None,
    )

    async def read(size):
        return b"not an image"

    upload.read = read

    with pytest.raises(HTTPException) as exc_info:
        await character_admin.upload_character_avatar(
            "npc-1",
            upload,
            current_user_id="user-1",
        )

    assert exc_info.value.status_code == 400
    assert "无效" in exc_info.value.detail
    assert saved == {}


@pytest.mark.asyncio
async def test_character_avatar_upload_normalization_runs_in_threadpool(monkeypatch):
    from memoria.api import character_admin

    source = io.BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(source, format="PNG")
    calls = []
    saved = {}

    async def run_in_threadpool(func, *args):
        calls.append(func)
        return func(*args)

    monkeypatch.setattr(character_admin, "run_in_threadpool", run_in_threadpool)
    monkeypatch.setattr(
        character_admin.repository,
        "get_character_card_from_db",
        lambda *args, **kwargs: {"character_id": "npc-1"},
    )
    monkeypatch.setattr(
        character_admin.repository,
        "update_character_avatar",
        lambda owner, character_id, avatar_url: saved.update(avatar_url=avatar_url),
    )
    upload = SimpleNamespace(content_type="image/png")

    async def read(size):
        if size == -1:
            return b""
        data, source_bytes[:] = bytes(source_bytes), b""
        return data

    source_bytes = bytearray(source.getvalue())
    upload.read = read

    await character_admin.upload_character_avatar(
        "npc-1",
        upload,
        current_user_id="user-1",
    )

    assert calls == [character_admin.avatar_data_url]
    assert saved["avatar_url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_user_avatar_upload_normalization_runs_in_threadpool(monkeypatch):
    from memoria.api import user

    source = io.BytesIO()
    Image.new("RGB", (2, 2), (0, 255, 0)).save(source, format="PNG")
    calls = []
    saved = {}

    async def run_in_threadpool(func, *args):
        calls.append(func)
        return func(*args)

    monkeypatch.setattr(user, "run_in_threadpool", run_in_threadpool)
    monkeypatch.setattr(
        user.repository,
        "update_user_profile",
        lambda uid, avatar_url=None, **kwargs: saved.update(avatar_url=avatar_url),
    )
    upload = SimpleNamespace(content_type="image/png")

    async def read(size):
        if size == -1:
            return b""
        data, source_bytes[:] = bytes(source_bytes), b""
        return data

    source_bytes = bytearray(source.getvalue())
    upload.read = read

    await user.upload_avatar(upload, uid="user-1")

    assert calls == [user._avatar_data_url]
    assert saved["avatar_url"].startswith("data:image/png;base64,")


def test_character_avatar_download_is_scheduled_and_only_replaces_source_url(monkeypatch):
    from memoria.api import character_admin

    writes = []
    monkeypatch.setattr(
        character_admin,
        "_download_avatar_sync",
        lambda url: "data:image/png;base64,downloaded",
    )
    monkeypatch.setattr(
        character_admin.repository,
        "update_character_avatar_if_current",
        lambda owner_user_id, character_id, expected_avatar_url, expected_revision, avatar_url: writes.append(
            (
                owner_user_id,
                character_id,
                expected_avatar_url,
                expected_revision,
                avatar_url,
            )
        ),
    )
    background_tasks = BackgroundTasks()

    character_admin._schedule_avatar_download(
        background_tasks,
        "user-1",
        "npc-1",
        "https://example.test/avatar.png",
        "revision-1",
    )

    assert writes == []
    assert len(background_tasks.tasks) == 1

    task = background_tasks.tasks[0]
    task.func(*task.args, **task.kwargs)

    assert writes == [
        (
            "user-1",
            "npc-1",
            "https://example.test/avatar.png",
            "revision-1",
            "data:image/png;base64,downloaded",
        )
    ]


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

    response = Response()
    res = user.login(user.LoginRequest(username="alice", password=password), response)

    assert res.user.user_id == "usr_test"
    assert updates["password_hash"].startswith("pbkdf2_sha256$")
    assert not hasattr(res, "token")
    assert tokens["token"] in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert tokens["user_id"] == "usr_test"


def test_get_current_user_id_reads_persistent_token_before_memory(monkeypatch):
    from memoria.api import user

    user._tokens.clear()
    monkeypatch.setattr(user.repository, "get_user_id_for_auth_token", lambda token: "usr_db")

    assert user.get_current_user_id("token") == "usr_db"


def test_admin_bootstrap_is_explicit_and_single_use(monkeypatch, tmp_path):
    from memoria.db import repository

    monkeypatch.setattr(repository.configs, "database_url", "")
    monkeypatch.setattr(repository.configs, "database_path", str(tmp_path / "bootstrap.db"))
    repository.init_db()

    assert repository.create_user(
        "usr_regular",
        "regular",
        "hash",
    ) is False
    assert repository.get_user_by_id("usr_regular")["is_admin"] == 0

    assert repository.create_user(
        "usr_admin",
        "admin",
        "hash",
        bootstrap_admin=True,
    ) is True
    assert repository.get_user_by_id("usr_admin")["is_admin"] == 1

    with pytest.raises(repository.AdminBootstrapUnavailable):
        repository.create_user(
            "usr_second_admin",
            "second_admin",
            "hash",
            bootstrap_admin=True,
        )
    assert repository.get_user_by_id("usr_second_admin") is None


def test_register_rejects_invalid_admin_bootstrap_token(monkeypatch):
    from memoria.api import user

    monkeypatch.setattr(user.configs, "admin_bootstrap_token", SecretStr("正确-token"))
    monkeypatch.setattr(
        user.repository,
        "get_user_by_username",
        lambda username: pytest.fail("invalid bootstrap must be rejected before database access"),
    )

    with pytest.raises(HTTPException) as exc_info:
        user.register(
            user.RegisterRequest(
                username="admin",
                password="password1",
                admin_bootstrap_token="错误-token",
            ),
            Response(),
        )

    assert exc_info.value.status_code == 403


def test_register_reports_consumed_admin_bootstrap(monkeypatch):
    from memoria.api import user

    monkeypatch.setattr(user.configs, "admin_bootstrap_token", SecretStr("correct-token"))
    monkeypatch.setattr(user.repository, "get_user_by_username", lambda username: None)
    monkeypatch.setattr(user.repository, "get_user_by_id", lambda user_id: None)
    monkeypatch.setattr(user, "_gen_user_id", lambda: "usr_admin")
    monkeypatch.setattr(user, "_hash_password", lambda password: "hash")
    monkeypatch.setattr(
        user.repository,
        "create_user",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            user.repository.AdminBootstrapUnavailable()
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        user.register(
            user.RegisterRequest(
                username="admin",
                password="password1",
                admin_bootstrap_token="correct-token",
            ),
            Response(),
        )

    assert exc_info.value.status_code == 409


def test_auth_tokens_are_stored_as_digests(monkeypatch, tmp_path):
    from memoria.db import repository

    monkeypatch.setattr(repository.configs, "database_url", "")
    monkeypatch.setattr(repository.configs, "database_path", str(tmp_path / "tokens.db"))
    repository.init_db()
    repository.create_user("usr_token", "token_user", "hash")

    raw_token = "raw-secret-token"
    repository.create_auth_token(raw_token, "usr_token", "9999-01-01T00:00:00+00:00")

    with repository.get_conn() as conn:
        rows = conn.execute("SELECT token FROM auth_token").fetchall()

    assert [row["token"] for row in rows] == [
        repository._auth_token_storage_key(raw_token)
    ]
    assert repository.get_user_id_for_auth_token(raw_token) == "usr_token"


def test_legacy_plaintext_auth_token_is_migrated_on_read(monkeypatch, tmp_path):
    from memoria.db import repository

    monkeypatch.setattr(repository.configs, "database_url", "")
    monkeypatch.setattr(repository.configs, "database_path", str(tmp_path / "legacy_token.db"))
    repository.init_db()
    repository.create_user("usr_legacy", "legacy_user", "hash")

    raw_token = "legacy-plaintext-token"
    with repository.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO auth_token (token, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                raw_token,
                "usr_legacy",
                "2026-01-01T00:00:00+00:00",
                "9999-01-01T00:00:00+00:00",
            ),
        )

    assert repository.get_user_id_for_auth_token(raw_token) == "usr_legacy"

    with repository.get_conn() as conn:
        rows = conn.execute("SELECT token FROM auth_token").fetchall()
    assert [row["token"] for row in rows] == [
        repository._auth_token_storage_key(raw_token)
    ]


def test_delete_auth_token_removes_digest_and_legacy_keys(monkeypatch, tmp_path):
    from memoria.db import repository

    monkeypatch.setattr(repository.configs, "database_url", "")
    monkeypatch.setattr(repository.configs, "database_path", str(tmp_path / "delete_token.db"))
    repository.init_db()
    repository.create_user("usr_logout", "logout_user", "hash")

    raw_token = "logout-token"
    repository.create_auth_token(raw_token, "usr_logout", "9999-01-01T00:00:00+00:00")
    with repository.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO auth_token (token, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                raw_token,
                "usr_logout",
                "2026-01-01T00:00:00+00:00",
                "9999-01-01T00:00:00+00:00",
            ),
        )

    repository.delete_auth_token(raw_token)

    with repository.get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) AS count FROM auth_token").fetchone()["count"]
    assert count == 0


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
    http_client = object()

    class FakeOpenAI:
        def __init__(self, base_url, api_key, http_client):
            created["base_url"] = base_url
            created["api_key"] = api_key
            created["http_client"] = http_client

    monkeypatch.setattr(llm_client.configs, "llm_base_url", "https://main.test/v1")
    monkeypatch.setattr(llm_client.configs, "llm_api_key", SecretStr("main-key"))
    monkeypatch.setattr(llm_client.configs, "llm_light_base_url", "https://light.test/v1")
    monkeypatch.setattr(llm_client.configs, "llm_light_api_key", SecretStr("light-key"))
    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm_client, "_build_http_client", lambda base_url: http_client)
    monkeypatch.setattr(llm_client, "_resolve_http_proxy", lambda base_url: None)
    monkeypatch.setattr(llm_client, "_client", None)
    monkeypatch.setattr(llm_client, "_light_client", None)
    monkeypatch.setattr(llm_client, "_light_client_signature", None)

    client = llm_client._get_light_client()

    assert isinstance(client, FakeOpenAI)
    assert created == {
        "base_url": "https://light.test/v1",
        "api_key": "light-key",
        "http_client": http_client,
    }


def test_llm_http_client_prefers_scheme_proxy_over_all_proxy(monkeypatch):
    from memoria.core import llm_client

    created = {}

    class FakeHttpClient:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr(
        llm_client,
        "getproxies",
        lambda: {
            "https": "http://127.0.0.1:7890/",
            "all": "socks://127.0.0.1:7890/",
        },
    )
    monkeypatch.setattr(llm_client, "proxy_bypass", lambda host: False)
    monkeypatch.setattr(llm_client, "DefaultHttpxClient", FakeHttpClient)
    monkeypatch.setattr(
        llm_client.inspect,
        "signature",
        lambda callable_obj: SimpleNamespace(parameters={"proxy": object()}),
    )

    client = llm_client._build_http_client("https://api.deepseek.test/v1")

    assert isinstance(client, FakeHttpClient)
    assert created == {
        "trust_env": False,
        "proxy": "http://127.0.0.1:7890/",
    }


def test_llm_http_client_supports_legacy_httpx_proxy_parameter(monkeypatch):
    from memoria.core import llm_client

    created = {}

    class FakeHttpClient:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr(
        llm_client,
        "_resolve_http_proxy",
        lambda base_url: "http://127.0.0.1:7890/",
    )
    monkeypatch.setattr(llm_client, "DefaultHttpxClient", FakeHttpClient)
    monkeypatch.setattr(
        llm_client.inspect,
        "signature",
        lambda callable_obj: SimpleNamespace(parameters={"proxies": object()}),
    )

    client = llm_client._build_http_client("https://api.deepseek.test/v1")

    assert isinstance(client, FakeHttpClient)
    assert created == {
        "trust_env": False,
        "proxies": "http://127.0.0.1:7890/",
    }


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


def test_retry_call_does_not_retry_non_retryable_4xx(monkeypatch):
    from memoria.core import llm_client

    attempts = []
    request = httpx.Request("POST", "https://api.example.test/v1/chat")
    response = httpx.Response(400, request=request)
    error = llm_client.APIStatusError("bad request", response=response, body={})
    monkeypatch.setattr(
        llm_client._time,
        "sleep",
        lambda delay: pytest.fail(f"unexpected retry delay: {delay}"),
    )

    def fail():
        attempts.append(1)
        raise error

    with pytest.raises(llm_client.APIStatusError):
        llm_client._retry_call(fail)

    assert len(attempts) == 1


@pytest.mark.parametrize("status_code", [429, 500])
def test_retry_call_retries_rate_limit_and_server_errors(monkeypatch, status_code):
    from memoria.core import llm_client

    attempts = []
    delays = []
    request = httpx.Request("POST", "https://api.example.test/v1/chat")
    response = httpx.Response(status_code, request=request)
    error = llm_client.APIStatusError("retryable", response=response, body={})
    monkeypatch.setattr(llm_client._time, "sleep", delays.append)

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise error
        return "ok"

    assert llm_client._retry_call(flaky) == "ok"
    assert len(attempts) == 3
    assert delays == [1.0, 2.0]


@pytest.mark.asyncio
async def test_read_upload_limited_reads_once_and_rejects_oversize():
    from memoria.api.upload_utils import read_upload_limited

    class FakeUpload:
        def __init__(self, data):
            self.data = data
            self.read_sizes = []

        async def read(self, size):
            self.read_sizes.append(size)
            return self.data[:size]

    upload = FakeUpload(b"123456")
    with pytest.raises(HTTPException) as exc_info:
        await read_upload_limited(upload, 5, detail="too large")

    assert exc_info.value.status_code == 413
    assert upload.read_sizes == [6]


def test_production_forces_auth_cookie_secure(monkeypatch):
    from memoria.core import config as config_module

    monkeypatch.setenv("MEMORIA_ENV", "production")
    monkeypatch.delenv("AUTH_COOKIE_SECURE", raising=False)
    config_module.get_config.cache_clear()
    try:
        cfg = config_module.get_config()
        assert cfg.memoria_env == "production"
        assert cfg.auth_cookie_secure is True
    finally:
        config_module.get_config.cache_clear()


def test_production_disables_in_memory_token_fallback(monkeypatch):
    from memoria.api import user
    from memoria.core.config import configs

    user._tokens.clear()
    user._tokens["legacy-token"] = "usr_mem"
    monkeypatch.setattr(user.repository, "get_user_id_for_auth_token", lambda token: None)
    monkeypatch.setattr(configs, "memoria_env", "production")

    assert user.get_current_user_id("legacy-token") is None

    monkeypatch.setattr(configs, "memoria_env", "development")
    assert user.get_current_user_id("legacy-token") == "usr_mem"
    user._tokens.clear()


def test_development_keeps_auth_cookie_secure_default_false(monkeypatch):
    from memoria.core import config as config_module

    monkeypatch.setenv("MEMORIA_ENV", "development")
    monkeypatch.delenv("AUTH_COOKIE_SECURE", raising=False)
    config_module.get_config.cache_clear()
    try:
        cfg = config_module.get_config()
        assert cfg.memoria_env == "development"
        assert cfg.auth_cookie_secure is False
    finally:
        config_module.get_config.cache_clear()

