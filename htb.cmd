@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Run install.ps1 or install Python 3.9+.
  exit /b 1
)
python htb_app.py %*
