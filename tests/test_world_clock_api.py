from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import fastapi.dependencies.utils
import fastapi.routing
from fastapi import FastAPI

from memoria.api import user as user_api
from memoria.db import repository


UTC = timezone.utc


def _create_user(prefix: str) -> str:
    user_id = f"{prefix}_{uuid.uuid4().hex[:10]}"
    repository.create_user(
        user_id,
        f"{prefix}_{uuid.uuid4().hex[:8]}",
        "test-hash",
    )
    return user_id


@pytest.mark.asyncio
async def test_world_clock_http_api_auth_validation_sync_and_isolation(
    monkeypatch,
):
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(fastapi.routing, "run_in_threadpool", run_inline)
    monkeypatch.setattr(
        fastapi.dependencies.utils,
        "run_in_threadpool",
        run_inline,
    )
    player_a = _create_user("http_a")
    player_b = _create_user("http_b")
    token_a = f"token_{uuid.uuid4().hex}"
    token_b = f"token_{uuid.uuid4().hex}"
    expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    repository.create_auth_token(token_a, player_a, expires_at)
    repository.create_auth_token(token_b, player_b, expires_at)
    app = FastAPI()
    app.include_router(user_api.router, prefix="/api/v1")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        assert (await client.get("/api/v1/user/world-clock")).status_code == 401
        assert (await client.put(
            "/api/v1/user/world-clock",
            json={"time_scale": 2},
        )).status_code == 401
        assert (await client.post(
            "/api/v1/user/world-clock/sync",
        )).status_code == 401

        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}
        initial = await client.get(
            "/api/v1/user/world-clock",
            headers=headers_a,
        )
        assert initial.status_code == 200
        assert initial.json()["time_scale"] == 1

        updated = await client.put(
            "/api/v1/user/world-clock",
            headers=headers_a,
            json={"timezone": "Asia/Shanghai", "time_scale": 5},
        )
        assert updated.status_code == 200
        assert updated.json()["timezone"] == "Asia/Shanghai"
        assert updated.json()["time_scale"] == 5

        synced = await client.post(
            "/api/v1/user/world-clock/sync",
            headers=headers_a,
        )
        assert synced.status_code == 200
        assert synced.json()["time_scale"] == 5
        assert synced.json()["world_now"] == synced.json()["real_now"]

        invalid_timezone = await client.put(
            "/api/v1/user/world-clock",
            headers=headers_a,
            json={"timezone": "Mars/Olympus_Mons"},
        )
        assert invalid_timezone.status_code == 400
        invalid_scale = await client.put(
            "/api/v1/user/world-clock",
            headers=headers_a,
            json={"time_scale": 3},
        )
        assert invalid_scale.status_code == 400
        boolean_scale = await client.put(
            "/api/v1/user/world-clock",
            headers=headers_a,
            json={"time_scale": True},
        )
        assert boolean_scale.status_code == 422

        isolated = await client.get(
            "/api/v1/user/world-clock",
            headers=headers_b,
        )
        assert isolated.status_code == 200
        assert isolated.json()["timezone"] == "UTC"
        assert isolated.json()["time_scale"] == 1
