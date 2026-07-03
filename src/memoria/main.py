"""
应用入口

启动方式：
    uvicorn memoria.main:app --reload

职责：
1. FastAPI 应用初始化
2. 路由挂载
3. 静态资源服务
4. 数据库初始化
"""

import os

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from memoria.api.dialogue import router as dialogue_router
from memoria.api.character_admin import router as character_admin_router
from memoria.api.event_admin import router as event_admin_router
from memoria.api.relationship import router as relationship_router
from memoria.api.multi_dialogue import router as multi_dialogue_router
from memoria.db.repository import init_db

# =========================
# logging 配置
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

# =========================
# 路径定义
# =========================
PACKAGE_DIR = Path(__file__).parent
STATIC_DIR = PACKAGE_DIR / "static"

# =========================
# 生命周期管理（推荐方式）
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用启动/关闭生命周期管理
    """

    # ---------- startup ----------
    try:
        init_db()
        logger.info("数据库初始化成功")
    except Exception as e:
        logger.error("数据库初始化失败: %s", e, exc_info=True)
        raise
    
    yield
    
    # ---------- shutdown ----------
    logger.info("服务正在关闭...")
    

# =========================
# FastAPI app
# =========================
app = FastAPI(
    title = "角色模拟系统 - 验证Demo",
    version = "0.1.0",
    lifespan = lifespan,
)

# =========================
# 路由注册
# =========================
app.include_router(dialogue_router, prefix = "/api/v1")
app.include_router(multi_dialogue_router, prefix="/api/v1")
app.include_router(character_admin_router, prefix = "/api/v1")
app.include_router(event_admin_router, prefix="/api/v1")
app.include_router(relationship_router, prefix = "/api/v1")


# =========================
# 静态资源挂载
# =========================
if STATIC_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static"
    )
else:
    logger.warning("静态资源目录不存在: %s", STATIC_DIR)
    
    