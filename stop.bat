@echo off
rem bookswich - stop services (ports 8000 / 5173)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" %*
pause
