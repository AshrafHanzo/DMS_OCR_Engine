@echo off
REM Quick start script for OCR Editor - Backend + Frontend servers
REM Run this script to start both servers in new windows

echo.
echo ╔════════════════════════════════════════════════════════════════╗
echo ║    🚀 Multilingual OCR Editor - Quick Start Launcher          ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.

REM Get the directory where this script is located
cd /d "%~dp0"

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ ERROR: Python not found. Please install Python 3.8 or later.
    pause
    exit /b 1
)

echo ✓ Python found
echo.

REM Check if required files exist
if not exist "main.py" (
    echo ❌ ERROR: main.py not found in current directory
    pause
    exit /b 1
)

if not exist "serve_frontend.py" (
    echo ❌ ERROR: serve_frontend.py not found in current directory
    pause
    exit /b 1
)

if not exist "index.html" (
    echo ❌ ERROR: index.html not found in current directory
    pause
    exit /b 1
)

echo ✓ All required files found
echo.
echo Starting servers...
echo.

REM Start Backend API Server in new window
start "OCR Backend API (port 8000)" cmd /k "title OCR Backend API - port 8000 && python main.py"

echo ✓ Backend API server started in new window (port 8000)

REM Wait 2 seconds for backend to start
timeout /t 2 /nobreak >nul

REM Start Frontend Server in new window
start "OCR Frontend (port 8080)" cmd /k "title OCR Frontend - port 8080 && python serve_frontend.py"

echo ✓ Frontend server started in new window (port 8080)
echo.
echo ╔════════════════════════════════════════════════════════════════╗
echo ║  ✅ Both servers are now running!                             ║
echo ╠════════════════════════════════════════════════════════════════╣
echo ║  🌐 Frontend UI:  http://localhost:8080                        ║
echo ║  🔧 Backend API: http://localhost:8000                         ║
echo ║                                                                ║
echo ║  📖 API Docs:    http://localhost:8000/docs                    ║
echo ║                                                                ║
echo ║  ⏹️  To stop: Close the server windows or press Ctrl+C         ║
echo ║  📝 See FRONTEND_GUIDE.md for detailed instructions           ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.
echo Opening browser...

REM Try to open browser
timeout /t 3 /nobreak >nul
start http://localhost:8080

echo.
echo This window can be closed safely. The servers will keep running.
pause
