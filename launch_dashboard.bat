@echo off
title Sentinel Wildlife Deterrent System - Server & Dashboard
cd /d "%~dp0"

set YOLO_OFFLINE=true
set ULTRALYTICS_OFFLINE=1

echo ========================================================================
echo   SENTINEL WILDLIFE DETERRENT SYSTEM v2.0 - LAUNCHER
echo   ECE 3332: Microcontroller Project Lab - Group 8
echo ========================================================================
echo.

:: Attempt to open Windows Firewall TCP Port 5002 so External PCs on ESP32 Wi-Fi can connect
netsh advfirewall firewall show rule name="Sentinel Dashboard Port 5002" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="Sentinel Dashboard Port 5002" dir=in action=allow protocol=TCP localport=5002 profile=any >nul 2>&1
)

echo [1/3] Detecting Network IP Addresses for External PC Sharing...
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4 Address"') do (
    for /f "tokens=* delims= " %%b in ("%%a") do (
        echo       - External PC Upload URL: http://%%b:5002
    )
)
echo       - Primary Laptop URL (Live Camera + Full Control): http://127.0.0.1:5002
echo.

:: Launch default browser to http://127.0.0.1:5002 after 3 seconds in background
echo [2/3] Opening Dashboard in Browser (http://127.0.0.1:5002)...
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:5002"

echo [3/3] Starting Sentinel AI Server on 0.0.0.0:5002...
echo.

if exist "C:\wildlife_yolo\conda_env\python.exe" (
    "C:\wildlife_yolo\conda_env\python.exe" app.py
) else if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app.py
) else (
    python app.py
)

pause
