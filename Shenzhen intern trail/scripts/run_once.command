#!/bin/zsh
cd "$(dirname "$0")/.."
echo "[Shenzhen intern trail] 单次扫描"
PYTHONDONTWRITEBYTECODE=1 python3 -m src.cli scan || true
if [ -f runs/latest.html ]; then
  open runs/latest.html 2>/dev/null || true
fi
read -k 1 "?按任意键关闭窗口..."
