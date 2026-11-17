@echo off
chcp 65001 >nul
title IELTS Copilot - Local Desktop Assistant (F:\ielts-copilot)
echo ============================================================================
echo   IELTS COPILOT - KHOI DONG UNG DUNG DESKTOP OFFLINE (LENOVO LEGION 5)
echo ============================================================================

cd /d "%~dp0"
set OLLAMA_MODELS=F:\AI-Data\ollama\models
set HF_HOME=F:\AI-Data\huggingface
set PYTHONPATH=apps\backend

echo [1/3] Kiem tra tien trinh Backend cu tren cong 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr "127.0.0.1:8000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo [2/3] Khoi chay Local FastAPI Backend ngam tai http://127.0.0.1:8000 ...
start "IELTS_Copilot_Backend" /min ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo Doi Backend khoi dong (3 giay)...
timeout /t 3 /nobreak >nul

echo [3/3] Mo cua so Desktop App IELTS Copilot...
where msedge >nul 2>&1
if %errorlevel% equ 0 (
    start /wait msedge --app=http://127.0.0.1:8000 --window-size=1480,920
) else (
    start http://127.0.0.1:8000
    echo Nhan phim bat ky khi ban muon dong Backend Server...
    pause >nul
)

echo Dang dong tien trinh Backend de khong chay ngam...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr "127.0.0.1:8000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo Da dong hoan toan IELTS Copilot!
