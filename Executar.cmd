@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Executar.ps1" %*
exit /b %errorlevel%
