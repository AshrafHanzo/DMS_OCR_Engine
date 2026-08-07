# Quick start script for OCR Editor - Backend + Frontend servers
# Run: powershell -ExecutionPolicy Bypass -File start.ps1

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║    🚀 Multilingual OCR Editor - Quick Start Launcher          ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Get the directory where this script is located
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath

# Check if Python is available
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✓ Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ ERROR: Python not found. Please install Python 3.8 or later." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""

# Check if required files exist
$requiredFiles = @("main.py", "serve_frontend.py", "index.html")
$missingFiles = @()

foreach ($file in $requiredFiles) {
    if (Test-Path $file) {
        Write-Host "✓ $file found" -ForegroundColor Green
    } else {
        Write-Host "❌ $file not found" -ForegroundColor Red
        $missingFiles += $file
    }
}

if ($missingFiles.Count -gt 0) {
    Write-Host ""
    Write-Host "Missing files: $($missingFiles -join ', ')" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "Starting servers..." -ForegroundColor Yellow
Write-Host ""

# Start Backend API Server
Write-Host "Starting Backend API (port 8000)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
Set-Location '$scriptPath'
Write-Host '╔════════════════════════════════════════════════════════════════╗'
Write-Host '║           🔧 OCR Backend API Server (port 8000)              ║'
Write-Host '╚════════════════════════════════════════════════════════════════╝'
Write-Host ''
python main.py
Write-Host ''
Write-Host 'Press Ctrl+C to stop'
"@ -NoNewWindow -Wait

# Wait for backend to start
Start-Sleep -Seconds 2

Write-Host "✓ Backend API server started" -ForegroundColor Green
Write-Host ""

# Start Frontend Server
Write-Host "Starting Frontend Server (port 8080)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
Set-Location '$scriptPath'
Write-Host '╔════════════════════════════════════════════════════════════════╗'
Write-Host '║           🌐 OCR Frontend Server (port 8080)                 ║'
Write-Host '╚════════════════════════════════════════════════════════════════╝'
Write-Host ''
python serve_frontend.py
Write-Host ''
Write-Host 'Press Ctrl+C to stop'
"@

Write-Host "✓ Frontend server started" -ForegroundColor Green
Write-Host ""

# Display instructions
Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  ✅ Both servers are now running!                             ║" -ForegroundColor Green
Write-Host "╠════════════════════════════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "║  🌐 Frontend UI:  http://localhost:8080                        ║" -ForegroundColor Cyan
Write-Host "║  🔧 Backend API: http://localhost:8000                         ║" -ForegroundColor Cyan
Write-Host "║                                                                ║" -ForegroundColor Green
Write-Host "║  📖 API Docs:    http://localhost:8000/docs                    ║" -ForegroundColor Cyan
Write-Host "║  📖 OpenAPI:     http://localhost:8000/openapi.json            ║" -ForegroundColor Cyan
Write-Host "║                                                                ║" -ForegroundColor Green
Write-Host "║  ⏹️  To stop: Close the server windows or press Ctrl+C         ║" -ForegroundColor Yellow
Write-Host "║  📝 See FRONTEND_GUIDE.md for detailed instructions           ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""

# Try to open browser
Write-Host "Opening browser in 3 seconds..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

try {
    Start-Process "http://localhost:8080"
    Write-Host "✓ Browser opened" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Could not open browser automatically. Please visit: http://localhost:8080" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup complete! You can close this window." -ForegroundColor Green
Read-Host "Press Enter to exit"
