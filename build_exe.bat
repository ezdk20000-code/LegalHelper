@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Сборка PDF Мастер

echo ============================================
echo   PDF Мастер - сборка программы
echo ============================================
echo.

rem ---- 1. Поиск Python ----
set "PY="
where py >nul 2>&1 && (py -3 --version >nul 2>&1 && set "PY=py -3")
if not defined PY (
    where python >nul 2>&1 && (python --version >nul 2>&1 && set "PY=python")
)
if not defined PY (
    echo Python не найден. Пробую установить Python 3.12 через winget...
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo.
        echo Не удалось установить Python автоматически.
        echo Установите Python 3.10+ с https://www.python.org/downloads/
        echo ОБЯЗАТЕЛЬНО отметьте галочку "Add python.exe to PATH", затем запустите этот файл снова.
        pause
        exit /b 1
    )
    echo.
    echo Python установлен. Закройте это окно и запустите build_exe.bat ещё раз.
    pause
    exit /b 0
)
echo Найден Python: %PY%
%PY% --version

rem ---- 2. Виртуальное окружение ----
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Создаю виртуальное окружение...
    %PY% -m venv .venv
    if errorlevel 1 ( echo Ошибка создания venv & pause & exit /b 1 )
)
set "VPY=.venv\Scripts\python.exe"

echo.
echo Устанавливаю библиотеки (может занять несколько минут)...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 ( echo Ошибка установки библиотек. Проверьте интернет. & pause & exit /b 1 )

rem ---- 3. Языки для OCR ----
if not exist tessdata mkdir tessdata
for %%L in (rus eng) do (
    if not exist "tessdata\%%L.traineddata" (
        echo Скачиваю язык OCR: %%L
        powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/tesseract-ocr/tessdata_fast/raw/main/%%L.traineddata' -OutFile 'tessdata\%%L.traineddata'"
    )
)

rem ---- 4. Сборка exe ----
echo.
echo Собираю PDFMaster.exe ...
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --name PDFMaster --icon app.ico ^
  --add-data "app.ico;." --add-data "tessdata;tessdata" ^
  --collect-data pptx --collect-all pymupdf4llm --collect-all pdf2docx ^
  pdf_master.py
if errorlevel 1 ( echo Ошибка сборки. & pause & exit /b 1 )

if not exist "dist\PDFMaster\PDFMaster.exe" ( echo Не найден dist\PDFMaster\PDFMaster.exe & pause & exit /b 1 )
echo.
echo Программа собрана: %cd%\dist\PDFMaster\PDFMaster.exe

rem ---- 5. Установщик (Inno Setup) или ярлык ----
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"

if defined ISCC (
    echo.
    echo Найден Inno Setup - собираю установщик...
    "!ISCC!" installer.iss
    if not errorlevel 1 (
        echo.
        echo Готово! Установщик: %cd%\installer_output\PDFMaster_Setup.exe
        explorer "%cd%\installer_output"
        pause
        exit /b 0
    )
    echo Не удалось собрать установщик, создаю ярлык.
)

echo.
echo Создаю ярлык на рабочем столе...
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\PDF Мастер.lnk'); $s.TargetPath='%cd%\dist\PDFMaster\PDFMaster.exe'; $s.WorkingDirectory='%cd%\dist\PDFMaster'; $s.IconLocation='%cd%\dist\PDFMaster\PDFMaster.exe,0'; $s.Save()"
echo.
echo ============================================
echo  Готово! На рабочем столе появился ярлык "PDF Мастер".
echo  Папку dist\PDFMaster можно переносить куда угодно.
echo  (Для полноценного установщика поставьте Inno Setup 6
echo   с https://jrsoftware.org/isdl.php и запустите сборку снова.)
echo ============================================
explorer "%cd%\dist\PDFMaster"
pause
