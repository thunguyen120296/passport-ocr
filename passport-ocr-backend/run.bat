@echo off
cd /d "%~dp0"
echo Starting Passport OCR backend with: %~dp0venv\Scripts\python.exe
"%~dp0venv\Scripts\python.exe" -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
