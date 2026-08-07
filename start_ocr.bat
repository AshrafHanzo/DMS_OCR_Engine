@echo off
REM ╔════════════════════════════════════════════════════════════════╗
REM ║    🚀 Multilingual OCR Editor - Start Both Servers             ║
REM ║                                                                ║
REM ║    This script runs BOTH Frontend & Backend servers in one go  ║
REM ║    - Backend API: http://localhost:8000                        ║
REM ║    - Frontend UI: http://localhost:8080                        ║
REM ╚════════════════════════════════════════════════════════════════╝

cd /d "%~dp0"

echo.
echo ╔════════════════════════════════════════════════════════════════╗
echo ║    🚀 OCR Editor - Starting Servers                           ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ ERROR: Python not found!
    echo Please install Python 3.8+ or activate virtual environment
    pause
    exit /b 1
)

echo ✓ Python found
echo ✓ Current directory: %cd%
echo.

REM Check if required files exist
if not exist "ocr\main.py" (
    echo ❌ ERROR: ocr\main.py not found
    pause
    exit /b 1
)

if not exist "ocr\serve_frontend.py" (
    echo ❌ ERROR: ocr\serve_frontend.py not found
    pause
    exit /b 1
)

if not exist "ocr\venv\Scripts\activate.bat" (
    echo ❌ ERROR: Virtual environment not found at ocr\venv
    pause
    exit /b 1
)

echo ✓ All required files found
echo.
echo Starting servers (new windows will appear)...
echo.

REM Start Backend API Server in new window
echo [1/2] Starting Backend API Server...
start "OCR Backend API (localhost:8000)" cmd /k "cd ocr && .\venv\Scripts\activate.bat && python main.py"

REM Wait 2 seconds for backend to start
timeout /t 2 /nobreak >nul

REM Start Frontend Server in new window
echo [2/2] Starting Frontend Server...
start "OCR Frontend (localhost:8080)" cmd /k "cd ocr && .\venv\Scripts\activate.bat && python serve_frontend.py"

echo.
echo ✓ Both servers started!
echo.
echo ╔════════════════════════════════════════════════════════════════╗
echo ║  ✅ SERVERS ARE RUNNING                                       ║
echo ╠════════════════════════════════════════════════════════════════╣
echo ║                                                                ║
echo ║  🌐 Open in Browser:                                           ║
echo ║     http://localhost:8080                                      ║
echo ║                                                                ║
echo ║  📖 API Documentation:                                         ║
echo ║     http://localhost:8000/docs                                 ║
echo ║                                                                ║
echo ║  🔧 Backend API:                                               ║
echo ║     http://localhost:8000                                      ║
echo ║                                                                ║
echo ║  ⏹️  To stop: Close the server windows or press Ctrl+C         ║
echo ║                                                                ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.

REM Try to open browser after 3 seconds
timeout /t 3 /nobreak >nul
echo Opening browser...
start http://localhost:8080

echo.
echo This window can be closed. Servers will continue running.
echo.
pause
