#!/usr/bin/env python3
"""
构建 Memoria 便携发布包

用法（仓库根目录）:
    python scripts/build_release.py                 # 完整构建（含前端 npm build）
    python scripts/build_release.py --skip-web-build # 复用现有 web/dist，不重新构建前端
    python scripts/build_release.py --no-model       # 不打包本地嵌入模型（包更小，需联网下载）

产物: dist_release/memoria-<version>.zip 与 memoria-<version>.tar.gz

发布包布局（白名单复制，杜绝误带密钥/运行数据）::

    memoria-<version>/
    ├── start.py / start.sh / start.bat   # 一键启动
    ├── run.py                            # 静态服务入口 (uvicorn run:app)
    ├── RELEASE.md                        # 使用说明
    ├── requirements.txt / pyproject.toml / LICENSE / README.md
    ├── config/.env.example               # 仅模板，不含真实密钥
    ├── src/memoria/                      # 后端源码
    ├── web/dist/                         # 前端构建产物
    ├── models/sentence-transformers/all-MiniLM-L6-v2/  # 本地嵌入模型
    └── data/                             # 空目录骨架（sqlite_db/chroma_db/knowledge/speech）
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "dist_release"

MODEL_REL = Path("models/sentence-transformers/all-MiniLM-L6-v2")
DATA_SUBDIRS = ("sqlite_db", "chroma_db", "knowledge", "speech")

# 需要复制到包内的条目：(源相对路径, 包内目标相对路径)。
# release/ 下的发布文件在仓库内位于子目录，包内则放到包根（一键启动体验）。
INCLUDE = [
    ("src", "src"),
    ("pyproject.toml", "pyproject.toml"),
    ("requirements.txt", "requirements.txt"),
    ("LICENSE", "LICENSE"),
    ("README.md", "README.md"),
    ("config/.env.example", "config/.env.example"),
    ("web/dist", "web/dist"),
    ("release/run.py", "run.py"),
    ("release/start.py", "start.py"),
    ("release/start.sh", "start.sh"),
    ("release/start.bat", "start.bat"),
    ("release/RELEASE.md", "RELEASE.md"),
    ("docs", "docs"),
    ("scripts/chat.sh", "scripts/chat.sh"),
    ("scripts/cli_chat.py", "scripts/cli_chat.py"),
]


def log(msg: str) -> None:
    print(f"[build] {msg}")


def fail(msg: str) -> None:
    print(f"[build] 错误: {msg}", file=sys.stderr)
    sys.exit(1)


def read_version() -> str:
    """从 pyproject.toml 读取版本号（Python 3.10 无 tomllib，用正则解析）。"""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        fail("无法从 pyproject.toml 解析版本号")
    return match.group(1)


def build_frontend(skip: bool) -> None:
    dist = ROOT / "web" / "dist"
    if skip:
        if not (dist / "index.html").is_file():
            fail(f"--skip-web-build 但 {dist}/index.html 不存在")
        log("跳过前端构建，复用现有 web/dist")
        return
    if not (ROOT / "web" / "node_modules").is_dir():
        log("未找到 web/node_modules，将复用现有 web/dist")
        if not (dist / "index.html").is_file():
            fail("web/dist 缺失且无法构建前端（缺少 node_modules），请先 npm install")
        return
    log("正在构建前端 (npm run build) ...")
    proc = subprocess.run(["npm", "run", "build"], cwd=str(ROOT / "web"))
    if proc.returncode != 0:
        fail("前端构建失败，请检查 npm 输出")
    if not (dist / "index.html").is_file():
        fail("前端构建产物缺失 index.html")
    log("前端构建完成")


def _normalize_package_permissions(staging: Path) -> None:
    """发布包跨用户解压后必须可读；脚本统一 755，文档/数据统一 644。"""
    for rel, mode in (
        ("start.py", 0o755),
        ("start.sh", 0o755),
        ("start.bat", 0o755),
        ("run.py", 0o644),
        ("RELEASE.md", 0o644),
    ):
        target = staging / rel
        if target.exists():
            os.chmod(target, mode)
    for path in (staging / "scripts").rglob("*"):
        if path.is_file():
            os.chmod(path, 0o755 if path.suffix in {".sh", ".py"} else 0o644)


def assemble_staging(version: str, with_model: bool) -> Path:
    name = f"memoria-{version}"
    staging = OUT_DIR / name
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    for src_rel, dst_rel in INCLUDE:
        src = ROOT / src_rel
        dst = staging / dst_rel
        if not src.exists():
            fail(f"缺少打包条目: {src_rel}")
        if src.is_dir():
            shutil.copytree(
                src,
                dst,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        log(f"已复制: {src_rel} -> {dst_rel}")

    if with_model:
        src = ROOT / MODEL_REL
        if not src.is_dir():
            fail(f"缺少嵌入模型: {MODEL_REL}（可用 --no-model 跳过）")
        shutil.copytree(
            src,
            staging / MODEL_REL,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        log(f"已复制嵌入模型: {MODEL_REL}")

    _normalize_package_permissions(staging)

    if not with_model:
        release_md = staging / "RELEASE.md"
        original = release_md.read_text(encoding="utf-8")
        release_md.write_text(
            "> **注意**：本发布包使用 `--no-model` 构建，**未内置嵌入模型**。\n"
            "> 向量记忆与知识库需要联网从 HuggingFace 下载 "
            "`sentence-transformers/all-MiniLM-L6-v2`，或将模型放入 "
            "`models/sentence-transformers/all-MiniLM-L6-v2/` 后重启。\n\n"
            + original.replace(
                "本包已内置嵌入模型（`models/sentence-transformers/all-MiniLM-L6-v2`），"
                "向量记忆与知识库可离线使用。",
                "本包未内置嵌入模型，向量记忆与知识库首次使用需要联网下载模型。",
            ),
            encoding="utf-8",
        )
        log("已生成 --no-model 发布说明")

    for sub in DATA_SUBDIRS:
        dir_path = staging / "data" / sub
        dir_path.mkdir(parents=True, exist_ok=True)
        (dir_path / ".gitkeep").touch()
    log("已创建空数据目录骨架")

    return staging


def validate_package(staging: Path, *, with_model: bool = True) -> None:
    problems = []
    if (staging / ".env").exists():
        problems.append("包内不应包含 .env（真实密钥）")
    for sub in DATA_SUBDIRS:
        for item in (staging / "data" / sub).iterdir():
            if item.name != ".gitkeep":
                problems.append(f"data/{sub} 不应包含文件: {item.name}")
    if not (staging / "web" / "dist" / "index.html").is_file():
        problems.append("web/dist/index.html 缺失")
    if not (staging / "web" / "dist" / "assets").is_dir():
        problems.append("web/dist/assets 缺失")
    if not (staging / "start.py").is_file() or not (staging / "run.py").is_file():
        problems.append("一键启动器/入口缺失（release/ 下文件未正确映射到包根）")
    packaged_pyc = [
        item.relative_to(staging)
        for item in staging.rglob("*.pyc")
    ]
    if packaged_pyc:
        problems.append(f"包内不应包含 .pyc: {len(packaged_pyc)} 个")
    if any((staging / rel).stat().st_mode & 0o444 == 0 for rel in ("start.py", "start.sh", "run.py")):
        problems.append("启动脚本/入口不可读（跨用户解压后无法执行）")
    if with_model and not (staging / MODEL_REL / "model.safetensors").is_file():
        problems.append(f"嵌入模型文件缺失: {MODEL_REL}/model.safetensors")
    if problems:
        for problem in problems:
            print(f"[build] 校验失败: {problem}")
        fail("发布包校验未通过")
    log("发布包校验通过（无 .env、无运行数据、前端与模型完整）" if with_model else "发布包校验通过（无 .env、无运行数据、前端完整，未打包模型）")


def make_archives(version: str) -> list[Path]:
    name = f"memoria-{version}"
    zip_path = OUT_DIR / f"{name}.zip"
    tar_path = OUT_DIR / f"{name}.tar.gz"

    if zip_path.exists():
        zip_path.unlink()
    if tar_path.exists():
        tar_path.unlink()

    shutil.make_archive(
        str(OUT_DIR / name),
        "zip",
        root_dir=str(OUT_DIR),
        base_dir=name,
    )
    shutil.make_archive(
        str(OUT_DIR / name),
        "gztar",
        root_dir=str(OUT_DIR),
        base_dir=name,
    )

    # 校验 zip 完整性（顶层应包含单个目录）
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad is not None:
            fail(f"zip 完整性校验失败: {bad}")
        top_dirs = {p.split("/")[0] for p in zf.namelist()}
        if top_dirs != {name}:
            fail(f"zip 顶层结构异常: {top_dirs}")

    return [zip_path, tar_path]


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 Memoria 便携发布包")
    parser.add_argument("--skip-web-build", action="store_true", help="复用现有 web/dist")
    parser.add_argument("--no-model", action="store_true", help="不打包本地嵌入模型")
    args = parser.parse_args()

    version = read_version()
    log(f"版本: {version}")
    build_frontend(args.skip_web_build)
    staging = assemble_staging(version, with_model=not args.no_model)
    validate_package(staging, with_model=not args.no_model)
    archives = make_archives(version)
    for archive in archives:
        size_mb = archive.stat().st_size / 1024 / 1024
        log(f"已生成: {archive} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    sys.exit(main())
