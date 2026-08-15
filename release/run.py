"""
发布包 Web 入口（叠加式静态服务）

在 ``memoria.main`` 之上追加前端静态资源服务，使单个 uvicorn 进程同时
提供 Web 页面与 /api 接口，无需额外部署 nginx。

启动方式：
- 发布包内（run.py 位于包根）:  ``uvicorn run:app --host 127.0.0.1 --port 8001``
- 源码仓库内（本文件位于 release/）:  ``uvicorn release.run:app ...``

静态目录可通过环境变量 ``MEMORIA_WEB_DIST`` 覆盖（测试用），
默认取仓库/包根目录下的 ``web/dist``。行为细节见
``memoria.static_serving``。
"""

import sys
from pathlib import Path


def _find_root(start: Path) -> Path:
    """向上查找同时包含 src/ 与 web/ 的项目根（仓库内为 release/ 的上级，
    发布包内本文件位于包根，两者代码一致）。"""
    for candidate in (start, start.parent, start.parent.parent, start.parent.parent.parent):
        if (candidate / "src").is_dir() and (candidate / "web").is_dir():
            return candidate
    return start


# 本文件可能位于发布包根（run.py）或仓库 release/ 子目录。
_ROOT = _find_root(Path(__file__).resolve().parent)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 便携包不保证 venv 中已安装项目本身（pip install -r requirements.txt
# 只装第三方依赖），因此把 src 加入 sys.path，与 scripts/cli_chat.py 同款做法。
_SRC_DIR = _ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from memoria.main import app  # noqa: E402
from memoria.static_serving import install_static_routes, resolve_web_dist  # noqa: E402

install_static_routes(app, resolve_web_dist())
