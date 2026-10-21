@echo off
REM  Create/update database tables, then seed permissions, company and admin.
setlocal
cd /d "%~dp0\..\backend"
call .venv\Scripts\activate.bat

echo.
echo  Applying database migrations...
alembic upgrade head
if errorlevel 1 (
    echo.
    echo  ERROR: migration failed.
    echo  Is PostgreSQL running, and does DATABASE_URL in .env match its password?
    exit /b 1
)

echo.
echo  Seeding permissions, company and admin user...
python -m app.core.seed
echo.
endlocal
