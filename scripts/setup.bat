@echo off
REM ===================================================================
REM  Jezseem ERP - one-time setup (Windows)
REM  Run this once from the project root:  scripts\setup.bat
REM ===================================================================
setlocal
cd /d "%~dp0\.."

echo.
echo  [1/4] Checking .env
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo        Created .env from .env.example
    echo.
    echo        ^>^> EDIT .env NOW and set:
    echo           POSTGRES_PASSWORD, the same password inside DATABASE_URL,
    echo           SECRET_KEY, and SEED_ADMIN_PASSWORD
    echo.
    pause
) else (
    echo        .env already exists - leaving it alone
)

echo.
echo  [2/4] Creating Python virtual environment
if not exist "backend\.venv" (
    python -m venv backend\.venv
    if errorlevel 1 (
        echo        ERROR: could not create venv. Is Python 3.11+ on your PATH?
        exit /b 1
    )
) else (
    echo        backend\.venv already exists
)

echo.
echo  [3/4] Installing Python packages
call backend\.venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r backend\requirements.txt
if errorlevel 1 (
    echo        ERROR: pip install failed. See the output above.
    exit /b 1
)

echo.
echo  [4/4] Installing frontend packages
cd frontend
call npm install
if errorlevel 1 (
    echo        ERROR: npm install failed. Is Node.js LTS installed?
    exit /b 1
)
cd ..

echo.
echo  Setup complete.
echo.
echo  Next:
echo    1. Make sure PostgreSQL is running
echo         - installed natively, OR
echo         - docker compose up -d      (database only)
echo    2. scripts\migrate.bat           (create tables + seed data)
echo    3. scripts\dev.bat               (start the app)
echo.
endlocal
