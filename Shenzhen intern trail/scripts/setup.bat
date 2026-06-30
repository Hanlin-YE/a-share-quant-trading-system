@echo off
cd /d "%~dp0\.."
echo [Shenzhen intern trail] setup

where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 Python。请先安装 Python 3.11+ 并勾选 Add Python to PATH。
  pause
  exit /b 1
)

python -c "import sys; assert sys.version_info >= (3,11), 'Python version too old'; print('Python OK:', sys.version.split()[0])"
if errorlevel 1 (
  pause
  exit /b 1
)

if not exist .env (
  copy .env.example .env >nul
  echo 已创建 .env，请填写 DEEPSEEK_API_KEY 后再运行。
) else (
  echo .env 已存在。
)

echo 正在检查 DeepSeek、行情源、新闻源...
set PYTHONDONTWRITEBYTECODE=1
python -m src.cli doctor
if errorlevel 1 echo 如果状态为 BLOCKED，请按提示检查 .env 或网络。
pause
