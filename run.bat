@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment missing. Run: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)
start "" http://127.0.0.1:8765
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
pause
