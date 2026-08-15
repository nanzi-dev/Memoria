@echo off
rem Memoria 一键启动（Windows）
rem 用法: start.bat [--host H] [--port P] [--no-install] [--skip-env]
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [start] 错误: 未找到 python，请先安装 Python 3.10+ 并加入 PATH
    pause
    exit /b 1
)

python start.py %*
