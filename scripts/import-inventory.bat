@echo off
REM  Imports the legacy inventory Excel exports from data\inventory\
setlocal
cd /d "%~dp0\..\backend"
call .venv\Scripts\activate.bat
python -m app.inventory.import_legacy
endlocal
