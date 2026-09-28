@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title PDF Master - установка и обновление
cd /d "%~dp0"

rem =====================================================================
rem  Установка ИЛИ обновление PDF Мастер (один и тот же файл).
rem  Сборка идёт в %LOCALAPPDATA%\PDFMaster-build (библиотеки ставятся
rem  один раз, следующие обновления быстрые). Готовая программа
rem  заменяет установленную - там, где она уже стоит.
rem =====================================================================

set "SRC=%~dp0."
set "WORK=%LOCALAPPDATA%\PDFMaster-build"
set "BSRC=%WORK%\src"
set "VPY=%WORK%\.venv\Scripts\python.exe"
set "PORTABLE=%LOCALAPPDATA%\Programs\PDFMaster"
set "APPID={7C2E8F4A-3B1D-4E9A-9F21-5D6A0B8C4E11}_is1"
set "LOG=%WORK%\update.log"

if not exist "%SRC%\pdf_master.py" (
    echo Не найден pdf_master.py рядом с update.bat.
    echo Распакуйте архив полностью и запустите update.bat из распакованной папки.
    goto :fail
)
if not exist "%WORK%" mkdir "%WORK%"

echo ============================================
echo   PDF Мастер - установка / обновление
echo ============================================
echo.

rem ---------- 1. Python ----------
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY if exist "%VPY%" set "PY=%VPY%"
if not defined PY (
    echo Python не найден. Пробую установить Python 3.12 через winget...
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    echo.
    echo Если Python установился - закройте окно и запустите update.bat ещё раз.
    echo Иначе установите Python 3.10+ с https://www.python.org/downloads/
    echo и отметьте галочку "Add python.exe to PATH".
    goto :fail
)

rem ---------- 2. Копирую исходники в папку сборки ----------
echo [1/5] Копирую файлы новой версии...
robocopy "%SRC%" "%BSRC%" /E /XD .venv dist build installer_output __pycache__ /XF *.spec /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 ( echo Ошибка копирования файлов. & goto :fail )

set "VER="
for /f "tokens=2 delims==" %%V in ('findstr /B /C:"APP_VERSION" "%BSRC%\pdf_master.py"') do set "VER=%%V"
if defined VER for %%A in (!VER!) do set "VER=%%~A"
if not defined VER set "VER=1.0"
echo       Версия: %VER%

rem ---------- 3. Библиотеки ----------
echo [2/5] Проверяю библиотеки (первый раз - несколько минут)...
if not exist "%VPY%" (
    %PY% -m venv "%WORK%\.venv"
    if errorlevel 1 ( echo Не удалось создать окружение Python. & goto :fail )
)
"%VPY%" -m pip install --upgrade pip -q --disable-pip-version-check >>"%LOG%" 2>&1
"%VPY%" -m pip install -r "%BSRC%\requirements.txt" pyinstaller -q --disable-pip-version-check >>"%LOG%" 2>&1
if errorlevel 1 ( echo Ошибка установки библиотек - проверьте интернет. Подробности: %LOG% & goto :fail )

if not exist "%BSRC%\tessdata" mkdir "%BSRC%\tessdata"
for %%L in (rus eng) do if not exist "%BSRC%\tessdata\%%L.traineddata" (
    echo       Скачиваю язык OCR: %%L
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/tesseract-ocr/tessdata_fast/raw/main/%%L.traineddata' -OutFile '%BSRC%\tessdata\%%L.traineddata'"
)

rem ---------- 4. Сборка ----------
echo [3/5] Собираю программу...
pushd "%BSRC%"
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --log-level WARN --name PDFMaster --icon app.ico ^
  --add-data "app.ico;." --add-data "tessdata;tessdata" --add-data "excalidraw;excalidraw" --add-data "help;help" ^
  --collect-data pptx --collect-data docx --collect-all pymupdf4llm --collect-all pdf2docx --hidden-import case_tabs --hidden-import PySide6.QtWebEngineWidgets --hidden-import PySide6.QtWebEngineCore --hidden-import legal_ui --hidden-import legal_core --hidden-import cases --hidden-import legal_data --hidden-import templates_lib --hidden-import help_ui ^
  pdf_master.py >>"%LOG%" 2>&1
set "BERR=%errorlevel%"
popd
if not "%BERR%"=="0" ( echo Ошибка сборки. Подробности: %LOG% & goto :fail )
set "DIST=%BSRC%\dist\PDFMaster"
if not exist "%DIST%\PDFMaster.exe" ( echo Сборка не создала PDFMaster.exe. Подробности: %LOG% & goto :fail )

rem ---------- 5. Где стоит программа сейчас ----------
echo [4/5] Ищу установленную версию...
set "INST="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; foreach($r in 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'){ $p=Join-Path $r '%APPID%'; if(Test-Path -LiteralPath $p){ (Get-ItemProperty -LiteralPath $p).InstallLocation.TrimEnd('\'); break } }"`) do set "INST=%%I"

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"

echo       Закрываю PDF Мастер, если он открыт...
taskkill /IM PDFMaster.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo [5/5] Устанавливаю...
if defined ISCC goto :via_installer
if defined INST goto :via_copy_inst
set "TARGET=!INST!"
robocopy "!DIST!" "!TARGET!" /MIR /XF unins*.* /R:3 /W:2 /NFL /NDL /NJH /NJS /NP >nul
if not errorlevel 8 goto :copied
echo       Нужны права администратора - подтвердите запрос Windows...
> "%WORK%\copy_admin.cmd" echo @chcp 65001 ^>nul
>>"%WORK%\copy_admin.cmd" echo robocopy "!DIST!" "!TARGET!" /MIR /XF unins*.* /R:3 /W:2
powershell -NoProfile -Command "Start-Process -FilePath (Join-Path $env:WORK 'copy_admin.cmd') -Verb RunAs -Wait -WindowStyle Hidden"
:copied
if not exist "!TARGET!\PDFMaster.exe" ( echo Не удалось скопировать программу. & goto :fail )
goto :done

:via_portable

:via_installer
pushd "%BSRC%"
"!ISCC!" /Q /DMyAppVersion=%VER% installer.iss >>"%LOG%" 2>&1
set "IERR=!errorlevel!"
popd
if not "!IERR!"=="0" (
    echo Не удалось собрать установщик, ставлю копированием.
    if defined INST goto :via_copy_inst
    goto :via_portable
)
set "SETUP=%BSRC%\installer_output\PDFMaster_Setup.exe"
rem при обновлении установщик сам ставит туда же и с теми же правами, что и раньше
set "MODE="
if not defined INST set "MODE=/CURRENTUSER"
echo       Запускаю установщик (если Windows спросит разрешение - нажмите "Да")...
"!SETUP!" /SILENT /SUPPRESSMSGBOXES /NORESTART /NOCANCEL !MODE!
if errorlevel 1 ( echo Установщик завершился с ошибкой. & goto :fail )
if not defined INST (
    for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; foreach($r in 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'){ $p=Join-Path $r '%APPID%'; if(Test-Path -LiteralPath $p){ (Get-ItemProperty -LiteralPath $p).InstallLocation.TrimEnd('\'); break } }"`) do set "INST=%%I"
)
set "TARGET=!INST!"
goto :done

:via_copy_inst
set "TARGET=!INST!"
robocopy "!DIST!" "!TARGET!" /MIR /XF unins*.* /R:3 /W:2 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
    echo       Нужны права администратора - подтвердите запрос Windows...
    powershell -NoProfile -Command "Start-Process -FilePath robocopy -ArgumentList ('\"!DIST!\" \"!TARGET!\" /MIR /XF unins*.* /R:3 /W:2') -Verb RunAs -Wait -WindowStyle Hidden"
)
if not exist "!TARGET!\PDFMaster.exe" ( echo Не удалось скопировать программу в !TARGET! & goto :fail )
goto :done

:via_portable
set "TARGET=%PORTABLE%"
robocopy "!DIST!" "!TARGET!" /MIR /R:3 /W:2 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 ( echo Не удалось скопировать программу в !TARGET! & goto :fail )
rem ярлыки: рабочий стол и меню «Пуск» (старый ярлык с тем же именем заменяется)
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; foreach($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))){ $s=$ws.CreateShortcut((Join-Path $d 'PDF Мастер.lnk')); $s.TargetPath='!TARGET!\PDFMaster.exe'; $s.WorkingDirectory='!TARGET!'; $s.IconLocation='!TARGET!\PDFMaster.exe,0'; $s.Save() }"
goto :done

:done
echo.
echo ============================================
echo   Готово. Установлена версия %VER%
echo   Папка программы: !TARGET!
echo ============================================
if exist "!TARGET!\PDFMaster.exe" start "" "!TARGET!\PDFMaster.exe"
timeout /t 8
exit /b 0

:fail
echo.
echo ============================================
echo   Не получилось. Пришлите в чат текст из этого окна
echo   и файл журнала: %LOG%
echo ============================================
pause
exit /b 1
