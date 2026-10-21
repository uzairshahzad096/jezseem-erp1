@echo off
REM  Imports customers and contacts from data\partners\Contacts_Grid.xlsx
setlocal
cd /d "%~dp0\..\backend"
call .venv\Scripts\activate.bat
python -m app.partners.import_legacy
endlocal
