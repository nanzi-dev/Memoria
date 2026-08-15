"""
发布包静态资源服务（叠加式，无副作用）

在 FastAPI 应用之上追加前端静态资源服务，使单个 uvicorn 进程同时提供
Web 页面与 /api 接口，无需额外部署 nginx。入口见仓库根 ``run.py``：

    uvicorn run:app --host 127.0.0.1 --port 8001

设计要点：
- 本模块是纯函数库，导入不产生任何副作用（便于测试）；
- 后端 API 路由（/api、/docs、/health 等）在 main.py 中先于静态路由注册，
  Starlette 按注册顺序匹配，API 优先级天然更高；
- 同一 app 重复调用 ``install_static_routes`` 为幂等操作（app.state 标记）。
"""

import logging
import os
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("memoria.static")

# 这些路径属于后端 API / 文档，不应回退到 SPA 页面。
_API_PREFIXES = (
    "/api",
    "/admin",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/ready",
)

_STATIC_STATE_KEY = "memoria_static_installed"


def resolve_web_dist(default_dir: Path | None = None) -> Path:
    """解析前端构建产物目录。

    优先使用环境变量 ``MEMORIA_WEB_DIST``（测试用），
    否则返回 ``default_dir`` 或默认的 ``<仓库根>/web/dist``。
    """
    override = os.environ.get("MEMORIA_WEB_DIST", "").strip()
    if override:
        return Path(override).resolve()
    if default_dir is not None:
        return Path(default_dir).resolve()
    return (Path(__file__).resolve().parent.parent.parent / "web" / "dist").resolve()


def install_static_routes(app, dist: Path) -> None:
    """将 dist 目录挂载到 app；重复调用为幂等（不会重复注册路由）。

    Parameters
    ----------
    app:
        FastAPI 应用实例（如 ``memoria.main.app``）。
    dist:
        前端构建产物目录（含 index.html 与 assets/）。
    """
    if getattr(app.state, _STATIC_STATE_KEY, False):
        return
    app.state._memoria_static_installed = True

    dist = Path(dist)
    if not dist.is_dir():
        logger.warning("未找到前端构建产物 %s，仅以 API 模式运行", dist)
        return

    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
        logger.info("已挂载前端静态资源: %s", assets_dir)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if not full_path:
            return FileResponse(dist / "index.html")
        # 路径参数不含前导 "/"，补回后再做前缀判断
        if ("/" + full_path).startswith(_API_PREFIXES):
            return JSONResponse(
                status_code=404,
                content={"detail": "Not Found"},
            )
        candidate = (dist / full_path).resolve()
        if not candidate.is_relative_to(dist.resolve()):
            # 路径穿越防护：解析后必须仍位于 dist 目录内。
            return JSONResponse(
                status_code=404,
                content={"detail": "Not Found"},
            )
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

    logger.info("前端 SPA 回退已启用: %s", dist)
