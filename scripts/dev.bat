@echo off
REM  Starts backend and frontend in two windows.
setlocal
cd /d "%~dp0\.."

echo  Starting backend  -^> http://localhost:8000/api/docs
start "Jezseem ERP - Backend" cmd /k "cd /d %CD%\backend && .venv\Scripts\activate.bat && uvicorn app.main:app --reload --port 8000"

timeout /t 2 /nobreak >nul

echo  Starting frontend -^> http://localhost:3000
start "Jezseem ERP - Frontend" cmd /k "cd /d %CD%\frontend && npm run dev"

echo.
echo  Two windows opened. Close them to stop the servers.
echo  Open http://localhost:3000 in your browser.
echo.
endlocal
