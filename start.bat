@echo off
rem bookswich - start services (backend uvicorn + frontend vite)
rem usage: double-click, or: start.bat -NoBrowser  /  start.bat -Restart
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
pause
