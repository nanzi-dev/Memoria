"""
发布包静态服务（memoria.static_serving）测试。

用临时伪造的 dist 目录 + 独立 FastAPI 实例验证：
- 首页 / → index.html
- /assets/* → 静态构建产物
- 未知 SPA 路由 → 回退 index.html
- /api、/docs、/health 等后端路径 → 404 JSON（不被 SPA 回退吞掉）
- 路径穿越 → 404（不泄露 dist 外文件）
- 幂等：重复安装不会重复注册路由
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from memoria.static_serving import install_static_routes


def _make_app(dist):
    """构造带少量后端路由的独立应用（不触碰 memoria.main 的全局 app）。"""
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping():
        return {"pong": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    install_static_routes(app, dist)
    return app


def _make_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>memoria</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('memoria')", encoding="utf-8")
    (dist / "secret.txt").write_text("top-secret", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    return dist


def test_static_index(tmp_path):
    client = TestClient(_make_app(_make_dist(tmp_path)))
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.text == "<html>memoria</html>"


def test_static_assets(tmp_path):
    client = TestClient(_make_app(_make_dist(tmp_path)))
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert resp.text == "console.log('memoria')"


def test_existing_file_served_directly(tmp_path):
    client = TestClient(_make_app(_make_dist(tmp_path)))
    resp = client.get("/secret.txt")
    assert resp.status_code == 200
    assert resp.text == "top-secret"


def test_spa_fallback_returns_index(tmp_path):
    client = TestClient(_make_app(_make_dist(tmp_path)))
    for path in ("/characters", "/characters/npc-1/edit", "/multi-dialogue"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert resp.text == "<html>memoria</html>"


def test_backend_routes_not_shadowed(tmp_path):
    client = TestClient(_make_app(_make_dist(tmp_path)))
    assert client.get("/api/v1/ping").json() == {"pong": True}
    assert client.get("/health").json() == {"status": "ok"}


def test_unknown_api_returns_json_404(tmp_path):
    client = TestClient(_make_app(_make_dist(tmp_path)))
    resp = client.get("/api/v1/definitely-not-a-route")
    assert resp.status_code == 404
    assert "html" not in resp.text.lower()


def test_prefix_like_spa_route_is_not_mistaken_for_api(tmp_path):
    client = TestClient(_make_app(_make_dist(tmp_path)))
    resp = client.get("/adminfoo")
    assert resp.status_code == 200
    assert resp.text == "<html>memoria</html>"


def test_path_traversal_blocked(tmp_path):
    client = TestClient(_make_app(_make_dist(tmp_path)))
    # TestClient 会把裸 ../ 归一化掉，因此使用编码后的穿越路径锁定服务端防护。
    for path in ("/%2e%2e/outside.txt", "/..%2Foutside.txt"):
        resp = client.get(path)
        assert resp.status_code == 404
        assert resp.headers.get("content-type", "").startswith("application/json")
        assert "outside" not in resp.text


def test_install_is_idempotent(tmp_path):
    dist = _make_dist(tmp_path)
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping():
        return {"pong": True}

    install_static_routes(app, dist)
    install_static_routes(app, dist)
    install_static_routes(app, dist)

    client = TestClient(app)
    # 路由仍正常，且未因重复安装而堆积/报错
    assert client.get("/api/v1/ping").json() == {"pong": True}
    assert client.get("/some/spa/route").status_code == 200


def test_missing_dist_keeps_api_only(tmp_path):
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping():
        return {"pong": True}

    install_static_routes(app, tmp_path / "does-not-exist")
    client = TestClient(app)
    assert client.get("/api/v1/ping").json() == {"pong": True}
    assert client.get("/whatever").status_code == 404
