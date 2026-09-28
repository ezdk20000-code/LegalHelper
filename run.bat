@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "VPYW=%LOCALAPPDATA%\PDFMaster-build\.venv\Scripts\pythonw.exe"
if not exist "%VPYW%" (
    echo Сначала запустите update.bat - он установит всё необходимое.
    pause
    exit /b 1
)
start "" "%VPYW%" pdf_master.py %*
