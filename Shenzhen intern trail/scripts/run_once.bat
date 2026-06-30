@echo off
cd /d "%~dp0\.."
echo [Shenzhen intern trail] 单次扫描
set PYTHONDONTWRITEBYTECODE=1
python -m src.cli scan
if exist runs\latest.html start "" runs\latest.html
pause
