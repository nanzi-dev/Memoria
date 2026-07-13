"""
应用入口

启动方式：
    uvicorn memoria.main:app --reload
"""

import asyncio
import os
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from memoria.api.dialogue import router as dialogue_router
from memoria.api.character_admin import router as character_admin_router
from memoria.api.event_admin import router as event_admin_router
from memoria.api.relationship import router as relationship_router
from memoria.api.developer import router as developer_router
from memoria.api.multi_dialogue import router as multi_dialogue_router
from memoria.api.knowledge import router as knowledge_router
from memoria.api.user import (
    AUTH_COOKIE_NAME,
    get_current_user_id,
    router as user_router,
    require_current_user_id,
)
from memoria.core.config import configs
from memoria.core.event_runtime import (
    ensure_default_event_templates,
    run_world_clock_scheduler,
)
from memoria.core.knowledge_service import (
    process_knowledge_document,
    reconcile_knowledge_vectors,
    retry_knowledge_vector_cleanups,
)
from memoria.db import repository

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
APP_VERSION = "0.4.0"

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
# 速率限制（认证用户优先，未登录回退 IP）
# =========================
_request_counts: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 60.0   # 60 seconds
_RATE_LIMIT_MAX = 60        # max 60 requests per window

def _check_rate_limit(player_id: str) -> bool:
    """检查指定限流 key 是否允许请求。"""
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


def _get_rate_limit_key(request: Request) -> str:
    """优先使用认证用户做限流 key，避免客户端伪造 X-Player-ID 绕过。"""
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else None
    token = token or request.cookies.get(AUTH_COOKIE_NAME)

    if token:
        user_id = get_current_user_id(token)
        if user_id:
            return f"user:{user_id}"

    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}"


# =========================
# 生命周期管理
# =========================
def _resume_incomplete_knowledge_documents(
    stop_event: threading.Event | None = None,
) -> None:
    try:
        cleanup_result = retry_knowledge_vector_cleanups()
        reconciliation = reconcile_knowledge_vectors()
        logger.info(
            "知识向量对账完成: cleanup=%s reconciliation=%s",
            cleanup_result,
            reconciliation,
        )
    except Exception:
        logger.exception("知识向量清理或启动对账失败")
    documents = repository.list_incomplete_knowledge_documents()
    if not documents:
        return
    logger.warning("恢复 %s 个未完成的知识文档处理任务", len(documents))
    for document in documents:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            process_knowledge_document(
                document["owner_user_id"],
                document["document_id"],
                resume_processing=True,
                expected_status=document["status"],
                expected_updated_at=document["updated_at"],
            )
        except Exception:
            logger.exception(
                "恢复知识文档处理任务失败: document=%s",
                document["document_id"],
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---------- startup ----------
    config_errors = _validate_config()
    if config_errors:
        for err in config_errors:
            logger.warning("配置警告: %s", err)
    
    try:
        repository.init_db()
        ensure_default_event_templates()
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.error("数据库初始化失败: %s", e, exc_info=True)
        raise

    scheduler_task = asyncio.create_task(
        run_world_clock_scheduler(),
        name="memoria-world-clock-scheduler",
    )
    knowledge_recovery_stop = threading.Event()
    knowledge_recovery_thread = threading.Thread(
        target=_resume_incomplete_knowledge_documents,
        args=(knowledge_recovery_stop,),
        name="memoria-knowledge-document-recovery",
        daemon=True,
    )
    knowledge_recovery_thread.start()
    logger.info("Memoria 服务已启动 (v%s)", APP_VERSION)
    try:
        yield
    finally:
        # ---------- shutdown ----------
        scheduler_task.cancel()
        knowledge_recovery_stop.set()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        logger.info("Memoria 服务正在关闭...")


# =========================
# FastAPI app
# =========================
app = FastAPI(
    title="Memoria - 角色模拟系统",
    version=APP_VERSION,
    lifespan=lifespan,
)


# =========================
# 健康检查端点
# =========================
@app.get("/health", tags=["system"])
async def health():
    """存活检查：服务是否在运行"""
    return {"status": "ok", "version": APP_VERSION}


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
    """写操作速率限制中间件。"""
    # 仅对 API 写操作应用限流；列表、详情、历史等读请求不消耗窗口。
    if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
        rate_limit_key = _get_rate_limit_key(request)
        if not _check_rate_limit(rate_limit_key):
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
app.include_router(developer_router, prefix="/api/v1")
app.include_router(user_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1")
