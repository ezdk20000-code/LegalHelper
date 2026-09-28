@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Сначала запустите build_exe.bat - он установит всё необходимое.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" pdf_master.py %*
