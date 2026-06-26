@echo off
title Manga Memory AI Starter
echo ==========================================
echo       Starting Manga Memory AI Web App
echo ==========================================
echo.

:: Check if virtual environment exists
if exist ".venv\Scripts\activate.bat" (
    echo [INFO] Activating virtual environment...
    :: Start Flask server in a separate command window
    start "Manga Memory AI Server" cmd /k "call .venv\Scripts\activate && python src/web/app.py"
) else (
    echo [WARNING] .venv not found. Trying global python installation...
    start "Manga Memory AI Server" cmd /k "python src/web/app.py"
)

echo.
echo [INFO] Waiting 3 seconds for the server to spin up...
ping 127.0.0.1 -n 4 > nul

echo [INFO] Opening Web Dashboard in your browser...
start http://127.0.0.1:5000

echo.
echo ==========================================
echo Setup complete! You can close this window.
echo The server is running in the background.
echo ==========================================
ping 127.0.0.1 -n 3 > nul
