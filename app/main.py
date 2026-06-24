"""
应用入口

启动方式：
    uvicorn app.main:app --reload

职责：
1. FastAPI 应用初始化
2. 路由挂载
3. 静态资源服务
4. 数据库初始化
"""

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.dialogue import router as dialogue_router
from app.db.repository import init_db

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
BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "app" / "static"

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
    
    
# =========================
# 首页
# =========================
@app.get("/")
def serve_demo_page():
    """
    返回前端 demo 页面
    """
    index_file = STATIC_DIR / "index.html"

    if not index_file.exists():
        return FileResponse(
            path=None,
            content=b"index.html not found",
            media_type="text/plain"
        )

    return FileResponse(str(index_file))