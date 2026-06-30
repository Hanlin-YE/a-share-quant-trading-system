#!/bin/zsh
cd "$(dirname "$0")/.."
echo "[Shenzhen intern trail] 每 30 分钟自动扫描"
echo "关闭这个窗口即可停止。结果页面：runs/latest.html"
PYTHONDONTWRITEBYTECODE=1 python3 -m src.cli watch --interval-minutes 30
