@echo off
REM COVID-19 Analytics Dashboard - Windows Startup Script
REM Single command to install dependencies and run server

echo.
echo ========================================
echo COVID-19 Analytics Dashboard Launcher
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

echo [1/3] Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo [2/3] Checking data file...
if not exist "data\owid-covid-data.csv" (
    echo WARNING: OWID data file not found
    echo Please download from: https://github.com/owid/covid-19-data/blob/master/public/data/owid-covid-data.csv
    echo And save to: data\owid-covid-data.csv
    echo.
)

echo.
echo [3/3] Starting server...
echo.
python app.py

pause
