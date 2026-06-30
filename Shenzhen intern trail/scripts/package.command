#!/bin/zsh
set -e
cd "$(dirname "$0")/.."
PKG_NAME="Shenzhen-intern-trail-handoff-$(date +%Y%m%d-%H%M%S).zip"
echo "正在打包 $PKG_NAME"
zip -r "$PKG_NAME" . \
  -x "runs/*" \
  -x "logs/*" \
  -x "*/__pycache__/*" \
  -x "*.pyc" \
  -x ".pytest_cache/*" \
  -x "$PKG_NAME"
echo "打包完成：$PWD/$PKG_NAME"
echo "注意：此包保留 .env。只发给可信任的人。"
