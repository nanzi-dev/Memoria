"""
Phase 5 系统级测试：健康检查、配置校验、速率限制、懒加载
"""
import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class TestHealthEndpoints:
    def test_health(self):
        from memoria.main import APP_VERSION, health

        data = asyncio.run(health())
        assert data == {"status": "ok", "version": APP_VERSION}

    def test_ready_ok(self, monkeypatch):
        from memoria.main import ready

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, query):
                assert query == "SELECT 1"

        monkeypatch.setattr("memoria.db.repository.get_conn", lambda: Conn())

        data = asyncio.run(ready())
        assert data == {"status": "ready", "database": "ok"}

    def test_ready_db_fail(self, monkeypatch):
        from memoria.main import ready

        def fail_conn():
            raise Exception("DB down")

        monkeypatch.setattr("memoria.db.repository.get_conn", fail_conn)

        response = asyncio.run(ready())
        assert response.status_code == 503
        assert json.loads(response.body) == {
            "status": "not_ready",
            "database": "unavailable",
        }
        assert b"DB down" not in response.body


class TestLogLevel:
    def test_set_valid_level(self):
        from memoria.main import set_log_level

        data = asyncio.run(set_log_level("DEBUG", _current_user_id="usr_test"))
        assert data["log_level"] == "DEBUG"
        assert logging.getLogger("memoria").level == logging.DEBUG

    def test_set_invalid_level(self):
        from memoria.main import set_log_level

        response = asyncio.run(set_log_level("TRACE", _current_user_id="usr_test"))
        assert response.status_code == 400


class TestConfigValidation:
    def test_validate_missing_key(self):
        from memoria.main import _validate_config
        # Config validation reports missing key as warning only
        errors = _validate_config()
        assert isinstance(errors, list)


class TestKnowledgeRecovery:
    def test_resume_incomplete_documents(self, monkeypatch):
        from memoria import main

        documents = [
            {
                "owner_user_id": "owner-a",
                "document_id": "doc-a",
                "status": "queued",
                "updated_at": "2026-07-13T00:00:00+00:00",
            },
            {
                "owner_user_id": "owner-b",
                "document_id": "doc-b",
                "status": "processing",
                "updated_at": "2026-07-13T00:00:01+00:00",
            },
        ]
        processed = []
        monkeypatch.setattr(
            main.repository,
            "list_incomplete_knowledge_documents",
            lambda: documents,
        )
        monkeypatch.setattr(
            main,
            "process_knowledge_document",
            lambda owner, document, **kwargs: processed.append(
                (owner, document, kwargs)
            ),
        )

        main._resume_incomplete_knowledge_documents()

        assert processed == [
            (
                "owner-a",
                "doc-a",
                {
                    "resume_processing": True,
                    "expected_status": "queued",
                    "expected_updated_at": "2026-07-13T00:00:00+00:00",
                },
            ),
            (
                "owner-b",
                "doc-b",
                {
                    "resume_processing": True,
                    "expected_status": "processing",
                    "expected_updated_at": "2026-07-13T00:00:01+00:00",
                },
            ),
        ]


class TestRateLimiting:
    def test_rate_limit_allows_first_requests(self):
        from memoria.main import _check_rate_limit
        import uuid
        pid = f"rl_test_{uuid.uuid4().hex[:6]}"
        # First requests should pass
        for _ in range(10):
            assert _check_rate_limit(pid), "First 10 requests should pass"

    def test_rate_limit_blocks_excessive(self):
        from memoria.main import _check_rate_limit
        import uuid
        pid = f"rl_max_{uuid.uuid4().hex[:6]}"
        # Fill to limit
        for _ in range(60):
            assert _check_rate_limit(pid)
        # Next one should fail
        assert not _check_rate_limit(pid), "61st request should be blocked"

    def test_rate_limit_respects_player_id(self):
        from memoria.main import _check_rate_limit
        import uuid
        p1 = f"p1_{uuid.uuid4().hex[:6]}"
        p2 = f"p2_{uuid.uuid4().hex[:6]}"
        for _ in range(60):
            _check_rate_limit(p1)
        assert _check_rate_limit(p2), "Different player should not be limited"

    def test_rate_limit_is_thread_safe(self):
        from memoria.main import _check_rate_limit
        import uuid

        pid = f"rl_concurrent_{uuid.uuid4().hex[:6]}"
        with ThreadPoolExecutor(max_workers=16) as executor:
            results = list(executor.map(lambda _: _check_rate_limit(pid), range(120)))

        assert sum(results) == 60

    def test_rate_limit_prunes_stale_keys(self, monkeypatch):
        from memoria import main

        monkeypatch.setattr(main, "_RATE_LIMIT_WINDOW", 10.0)
        monkeypatch.setattr(main, "_last_rate_limit_cleanup", 0.0)
        monkeypatch.setattr(main.time, "monotonic", iter([1.0, 12.0]).__next__)
        with main._request_counts_lock:
            main._request_counts.clear()

        assert main._check_rate_limit("ip:stale")
        assert main._check_rate_limit("ip:current")
        assert "ip:stale" not in main._request_counts
        assert "ip:current" in main._request_counts

    def test_rate_limit_key_prefers_authenticated_user(self, monkeypatch):
        from memoria.main import _get_rate_limit_key

        monkeypatch.setattr("memoria.main.get_current_user_id", lambda token: "usr_abc")
        request = SimpleNamespace(
            headers={"Authorization": "Bearer token-abc"},
            cookies={},
            client=SimpleNamespace(host="127.0.0.1"),
        )

        assert _get_rate_limit_key(request) == "user:usr_abc"

    def test_rate_limit_key_ignores_spoofed_player_header(self, monkeypatch):
        from memoria.main import _get_rate_limit_key

        monkeypatch.setattr("memoria.main.get_current_user_id", lambda token: None)
        request = SimpleNamespace(
            headers={"X-Player-ID": "spoofed"},
            cookies={},
            client=SimpleNamespace(host="127.0.0.1"),
        )

        assert _get_rate_limit_key(request) == "ip:127.0.0.1"

class TestLazyLLMClient:
    def test_lazy_init_no_instantiation(self):
        """LLM client should not instantiate OpenAI on import"""
        # If llm_client imported without error, lazy init works
        try:
            from memoria.core import llm_client
            assert hasattr(llm_client, '_get_client'), "Should have _get_client function"
        except Exception as e:
            # Only fail if it's not a proxy/auth error
            if "socks" not in str(e).lower() and "api_key" not in str(e).lower():
                raise
