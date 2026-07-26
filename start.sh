#!/usr/bin/env bash
# fund_arb 统一启动入口（腾讯云轻量 / CloudBase Web 函数 通用）
# - 云函数会注入 PORT 环境变量，程序自动绑定 0.0.0.0
# - 轻量可手动指定 HOST/PORT，或保持默认（须用 systemd 注入 HOST=0.0.0.0 对外暴露）
set -e
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8000}"
exec python fund_arb.py
