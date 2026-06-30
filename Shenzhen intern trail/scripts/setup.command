#!/bin/zsh
set -e
cd "$(dirname "$0")/.."

echo "[Shenzhen intern trail] setup"

if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 python3。请先安装 Python 3.11+。"
  exit 1
fi

python3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 版本过低，请使用 Python 3.11+'; print('Python OK:', sys.version.split()[0])"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "已创建 .env，请填写 DEEPSEEK_API_KEY 后再运行。"
else
  echo ".env 已存在。"
fi

echo "正在检查 DeepSeek、行情源、新闻源..."
PYTHONDONTWRITEBYTECODE=1 python3 -m src.cli doctor || true

echo "setup 完成。若上方状态为 BLOCKED，请按提示检查 .env 或网络。"
read -k 1 "?按任意键关闭窗口..."
