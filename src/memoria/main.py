"""
应用入口

启动方式：
    uvicorn memoria.main:app --reload
"""

import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from memoria.api.dialogue import router as dialogue_router
from memoria.api.character_admin import router as character_admin_router
from memoria.api.event_admin import router as event_admin_router
from memoria.api.relationship import router as relationship_router
from memoria.api.multi_dialogue import router as multi_dialogue_router
from memoria.api.user import router as user_router, require_current_user_id
from memoria.db.repository import init_db
from memoria.core.config import configs
from memoria.core.event_runtime import ensure_default_event_templates

# =========================
# 结构化日志配置
# =========================
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("memoria")

# =========================
# 配置校验
# =========================
def _validate_config():
    """启动时校验必需配置项"""
    errors = []
    if not configs.llm_api_key.get_secret_value():
        errors.append("LLM_API_KEY 未配置（角色对话功能将不可用）")
    if not configs.llm_base_url:
        errors.append("LLM_BASE_URL 未配置")
    return errors


# =========================
# 速率限制（per-player 简单实现）
# =========================
_request_counts: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 60.0   # 60 seconds
_RATE_LIMIT_MAX = 60        # max 60 requests per window

def _check_rate_limit(player_id: str) -> bool:
    """检查 per-player 速率限制，返回 True 表示允许"""
    import time
    now = time.time()
    if player_id not in _request_counts:
        _request_counts[player_id] = []
    timestamps = _request_counts[player_id]
    # 清理过期记录
    timestamps[:] = [t for t in timestamps if now - t < _RATE_LIMIT_WINDOW]
    if len(timestamps) >= _RATE_LIMIT_MAX:
        return False
    timestamps.append(now)
    return True


# =========================
# 生命周期管理
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---------- startup ----------
    config_errors = _validate_config()
    if config_errors:
        for err in config_errors:
            logger.warning("配置警告: %s", err)
    
    try:
        init_db()
        ensure_default_event_templates()
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.error("数据库初始化失败: %s", e, exc_info=True)
        raise

    logger.info("Memoria 服务已启动 (v0.4.0)")
    yield
    # ---------- shutdown ----------
    logger.info("Memoria 服务正在关闭...")


# =========================
# FastAPI app
# =========================
app = FastAPI(
    title="Memoria - 角色模拟系统",
    version="0.4.0",
    lifespan=lifespan,
)


# =========================
# 健康检查端点
# =========================
@app.get("/health", tags=["system"])
async def health():
    """存活检查：服务是否在运行"""
    return {"status": "ok", "version": "0.4.0"}


@app.get("/ready", tags=["system"])
async def ready():
    """就绪检查：数据库等依赖是否可用"""
    try:
        from memoria.db.repository import get_conn
        with get_conn() as conn:
            conn.execute("SELECT 1")
        return {"status": "ready", "database": "ok"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": str(e)}
        )


# =========================
# 日志级别动态调整
# =========================
@app.post("/admin/log-level", tags=["system"])
async def set_log_level(level: str = "INFO", _current_user_id: str = Depends(require_current_user_id)):
    """动态调整日志级别（DEBUG/INFO/WARNING/ERROR）"""
    level = level.upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        return JSONResponse(status_code=400, content={"error": f"无效级别: {level}"})
    logging.getLogger("memoria").setLevel(getattr(logging, level))
    return {"log_level": level}


# =========================
# 速率限制中间件
# =========================
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """per-player 速率限制中间件"""
    # 仅对 API 写操作应用限流；列表、详情、历史等读请求不消耗窗口。
    if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
        player_id = request.headers.get("X-Player-ID", request.client.host if request.client else "unknown")
        if not _check_rate_limit(player_id):
            return JSONResponse(
                status_code=429,
                content={"error": "请求过于频繁，请稍后再试", "retry_after": _RATE_LIMIT_WINDOW}
            )
    return await call_next(request)


# =========================
# 路由注册
# =========================
app.include_router(dialogue_router, prefix="/api/v1")
app.include_router(multi_dialogue_router, prefix="/api/v1")
app.include_router(character_admin_router, prefix="/api/v1")
app.include_router(event_admin_router, prefix="/api/v1")
app.include_router(relationship_router, prefix="/api/v1")
app.include_router(user_router, prefix="/api/v1")
