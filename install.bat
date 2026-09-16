@echo off
setlocal
cd /d "%~dp0"
if not exist .venv (
  py -3.13 -m venv .venv || py -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if not exist .env if exist .env.example copy .env.example .env
echo.
echo Installation complete. Edit .env and set BOT_TOKEN if needed.
pause
