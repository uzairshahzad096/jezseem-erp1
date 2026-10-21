@echo off
REM  Applies the current SEED_ADMIN_PASSWORD from .env to the admin user.
setlocal
cd /d "%~dp0\..\backend"
call .venv\Scripts\activate.bat
python -m app.core.seed --reset-password
endlocal
