@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m creator_ops run-all %*
) else (
  python -m creator_ops run-all %*
)

exit /b %errorlevel%
