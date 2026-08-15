#!/usr/bin/env python3
"""
Memoria 一键启动器（跨平台）

用法:
    python start.py                # 首次运行自动建 venv、装依赖，然后启动服务
    python start.py --port 9000    # 指定端口
    python start.py --host 0.0.0.0 # 监听所有网卡（注意生产环境安全配置）
    python start.py --no-install   # 跳过依赖安装（已存在 .venv 时）
    python start.py --skip-env     # 不自动复制 .env 模板

启动后访问: http://127.0.0.1:8001  （默认端口 8001）
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _find_root(start: Path) -> Path:
    """向上查找同时包含 src/ 与 web/ 的项目根（仓库内本文件位于 release/，
    发布包内位于包根，两者代码一致）。"""
    for candidate in (start, start.parent, start.parent.parent, start.parent.parent.parent):
        if (candidate / "src").is_dir() and (candidate / "web").is_dir():
            return candidate
    return start


APP_ROOT = _find_root(Path(__file__).resolve().parent)

MIN_PYTHON = (3, 10)


def log(msg: str) -> None:
    print(f"[start] {msg}")


def fail(msg: str) -> None:
    print(f"[start] 错误: {msg}", file=sys.stderr)
    sys.exit(1)


def ensure_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        fail(
            f"需要 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+，当前为 "
            f"{sys.version_info.major}.{sys.version_info.minor}。"
            f"请先安装 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+。"
        )


def ensure_env_file(skip_env: bool) -> None:
    env_file = APP_ROOT / ".env"
    if env_file.exists():
        return
    example = APP_ROOT / "config" / ".env.example"
    if not example.exists():
        log("未找到 config/.env.example，跳过 .env 模板复制")
        return
    if skip_env:
        log("已跳过 .env 模板复制（--skip-env）")
        return
    shutil.copy2(example, env_file)
    log("已从 config/.env.example 创建 .env（请编辑填入 LLM_API_KEY 等密钥）")


def ensure_data_dirs() -> None:
    for sub in ("sqlite_db", "chroma_db", "knowledge", "speech"):
        (APP_ROOT / "data" / sub).mkdir(parents=True, exist_ok=True)
    log("数据目录已就绪: data/sqlite_db, data/chroma_db, data/knowledge, data/speech")


def venv_python() -> Path:
    if os.name == "nt":
        return APP_ROOT / ".venv" / "Scripts" / "python.exe"
    return APP_ROOT / ".venv" / "bin" / "python"


def run(cmd: list[str], cwd: Path, desc: str) -> None:
    log(f"{desc}: {' '.join(str(c) for c in cmd)}")
    proc = subprocess.run(cmd, cwd=str(cwd))
    if proc.returncode != 0:
        fail(f"{desc}失败（退出码 {proc.returncode}），请查看上方输出。")
    log(f"{desc}完成")


def ensure_venv(no_install: bool, venv: Path) -> None:
    if venv.exists():
        log(f"检测到现有虚拟环境: {venv}")
        return
    if no_install:
        fail("虚拟环境不存在且指定了 --no-install，无法启动。请去掉 --no-install 后重试。")
    log("首次运行：正在创建虚拟环境 .venv ...")
    run([sys.executable, "-m", "venv", str(venv)], APP_ROOT, "创建虚拟环境")
    log(
        "首次运行：正在安装依赖（torch / chromadb 等体积较大，"
        "需要联网且耗时较长，请耐心等待）..."
    )
    run(
        [str(venv_python()), "-m", "pip", "install", "--upgrade", "pip"],
        APP_ROOT,
        "升级 pip",
    )
    run(
        [str(venv_python()), "-m", "pip", "install", "-r", "requirements.txt"],
        APP_ROOT,
        "安装依赖",
    )
    # 安装项目本身（editable），保证任意目录下都能 `import memoria`
    run(
        [str(venv_python()), "-m", "pip", "install", "-e", "."],
        APP_ROOT,
        "安装项目包",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Memoria 一键启动器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8001, help="监听端口（默认 8001）")
    parser.add_argument("--no-install", action="store_true", help="跳过依赖安装")
    parser.add_argument("--skip-env", action="store_true", help="不自动复制 .env 模板")
    args = parser.parse_args()

    ensure_python_version()
    os.chdir(APP_ROOT)  # .env / ./data / ./models 相对路径依赖当前目录
    ensure_env_file(args.skip_env)
    ensure_data_dirs()

    venv = venv_python()
    ensure_venv(args.no_install, venv)

    if not venv.exists():
        fail("未找到虚拟环境 Python，无法启动。请去掉 --no-install 后重试。")

    url = f"http://{args.host}:{args.port}"
    log(f"正在启动 Memoria ... 访问地址: {url}")
    log("（请勿使用多 worker 运行：调度器与后台任务为单进程设计）")
    cmd = [
        str(venv),
        "-m",
        "uvicorn",
        "run:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    proc = subprocess.run(cmd, cwd=str(APP_ROOT))
    if proc.returncode != 0:
        fail(
            "服务启动失败。常见原因：端口被占用（换 --port 重试）、"
            ".env 中配置非法、依赖未装全。请查看上方错误输出。"
        )


if __name__ == "__main__":
    main()
