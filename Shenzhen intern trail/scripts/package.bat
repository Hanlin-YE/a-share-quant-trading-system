@echo off
cd /d "%~dp0\.."
set PKG_NAME=Shenzhen-intern-trail-handoff.zip
echo 正在打包 %PKG_NAME%
powershell -NoProfile -Command "$exclude=@('runs','logs','__pycache__','.pytest_cache'); $files=Get-ChildItem -Force | Where-Object { $exclude -notcontains $_.Name -and $_.Name -ne '%PKG_NAME%' }; Compress-Archive -Force -Path $files.FullName -DestinationPath '%PKG_NAME%'"
echo 打包完成：%PKG_NAME%
echo 注意：此包保留 .env。只发给可信任的人。
pause
