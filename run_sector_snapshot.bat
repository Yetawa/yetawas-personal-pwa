@echo off
setlocal EnableDelayedExpansion
REM ============================================================
REM  基金套利 · 行业轮动日更快照 定时执行脚本
REM  功能：收盘后拉取东财 -> 生成 sector_data.json -> push GitHub -> onrender 自动部署
REM  用法：直接双击运行，或由 Windows 任务计划程序（交易日 15:30）调用
REM ============================================================

REM ===== 配置区（一般无需改动）=====
set "REPO=D:\Workbuddy\yetawas-personal-pwa"
set "PY=C:\Users\USER\.workbuddy\binaries\python\versions\3.13.12\python.exe"
set "LOG=%REPO%\sector_snapshot.log"
REM 默认 ghproxy 镜像（符合「禁止直连 github.com」规则）。
REM 若本机 git 已全局配置过 insteadOf，脚本会自动跳过此项避免双重代理。
REM 若该镜像不通，改成你自己的镜像，如 https://ghproxy.com
set "GH_PROXY=https://ghproxy.net"
REM ============================================================

cd /d "%REPO%" || (echo %date% %time% CD_FAIL >> "%LOG%" & exit /b 1)
echo [%date% %time%] START >> "%LOG%"

REM 若本机已存在 github.com 的 insteadOf 配置，则不重复注入 GH_PROXY（防双重代理）
git config --get-regexp insteadOf 2>nul | findstr /i "github.com" >nul
if %errorlevel%==0 (
  set "USE_PROXY="
) else (
  set "USE_PROXY=%GH_PROXY%"
)
set "GH_PROXY=%USE_PROXY%"

"%PY%" "%REPO%\gen_sector_data.py" --push >> "%LOG%" 2>&1
set "RC=%errorlevel%"
echo [%date% %time%] END rc=%RC% >> "%LOG%"
exit /b %RC%
