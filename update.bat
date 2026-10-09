@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title LegalHelper - установка и обновление
cd /d "%~dp0"

rem =====================================================================
rem  Установка ИЛИ обновление LegalHelper (один и тот же файл).
rem  Сборка идёт в %LOCALAPPDATA%\PDFMaster-build (библиотеки ставятся
rem  один раз, следующие обновления быстрые). Готовая программа
rem  заменяет установленную - там, где она уже стоит.
rem =====================================================================

set "SRC=%~dp0."
set "WORK=%LOCALAPPDATA%\PDFMaster-build"
set "BSRC=%WORK%\src"
set "VPY=%WORK%\.venv\Scripts\python.exe"
set "PORTABLE=%LOCALAPPDATA%\Programs\LegalHelper"
rem  до версии 1.6 программа называлась «PDF Мастер» (PDFMaster.exe) - старые файлы и ярлыки заменяются
set "OLDPORTABLE=%LOCALAPPDATA%\Programs\PDFMaster"
set "APPID={7C2E8F4A-3B1D-4E9A-9F21-5D6A0B8C4E11}_is1"
set "LOG=%WORK%\update.log"

if not exist "%SRC%\pdf_master.py" (
    echo Похоже, файл запущен прямо из архива ZIP, не распакованного до конца.
    echo.
    echo Что сделать:
    echo 1. Закройте это окно.
    echo 2. Найдите скачанный архив LegalHelper-main.zip ^(обычно в папке "Загрузки"^).
    echo 3. Щёлкните по нему ПРАВОЙ кнопкой мыши - "Извлечь все..." - "Извлечь".
    echo 4. В открывшейся папке LegalHelper-main дважды щёлкните УСТАНОВИТЬ.bat
    goto :fail
)
if not exist "%WORK%" mkdir "%WORK%"

echo ============================================
echo   LegalHelper - установка / обновление
echo ============================================
echo.

rem ---------- 1. Python ----------
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY if exist "%VPY%" set "PY=%VPY%"
if not defined PY (
    echo Python не найден. Устанавливаю Python 3.12 ^(это нужно один раз^)...
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
    if not defined PY if exist "%ProgramFiles%\Python312\python.exe" set "PY="%ProgramFiles%\Python312\python.exe""
)
if not defined PY (
    echo.
    echo Python не установился автоматически.
    echo 1. Откройте https://www.python.org/downloads/ и нажмите "Download Python".
    echo 2. Запустите скачанный файл и ОБЯЗАТЕЛЬНО отметьте галочку "Add python.exe to PATH" внизу окна.
    echo 3. Нажмите "Install Now", дождитесь конца и снова запустите УСТАНОВИТЬ.bat
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
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --log-level WARN --name LegalHelper --icon app.ico ^
  --add-data "app.ico;." --add-data "tessdata;tessdata" --add-data "excalidraw;excalidraw" --add-data "help;help" --add-data "forms;forms" ^
  --collect-data pptx --collect-data docx --collect-all pymupdf4llm --collect-all pdf2docx --hidden-import case_tabs --hidden-import PySide6.QtWebEngineWidgets --hidden-import PySide6.QtWebEngineCore --hidden-import legal_ui --hidden-import legal_core --hidden-import cases --hidden-import legal_data --hidden-import templates_lib --hidden-import help_ui --hidden-import updater --hidden-import timecheck --hidden-import backup --hidden-import casefile --hidden-import anim --hidden-import timer_widget --hidden-import extwatch --hidden-import tutorial --hidden-import help_content --hidden-import phone_export --hidden-import palette --hidden-import app_menu --hidden-import modern_ui --hidden-import folders_ui --hidden-import laws_auto --hidden-import doc_names --hidden-import rename_ui --hidden-import outline_ui --hidden-import titlebar --hidden-import PySide6.QtQuickWidgets --hidden-import hearings --hidden-import hearings_ui --hidden-import kad_ui --hidden-import yacal --hidden-import yacal_ui --hidden-import zoom_ui --hidden-import practice_auto --hidden-import practice_ui --hidden-import word_editor ^
  pdf_master.py >>"%LOG%" 2>&1
set "BERR=%errorlevel%"
popd
if not "%BERR%"=="0" ( echo Ошибка сборки. Подробности: %LOG% & goto :fail )
set "DIST=%BSRC%\dist\LegalHelper"
if not exist "%DIST%\LegalHelper.exe" ( echo Сборка не создала LegalHelper.exe. Подробности: %LOG% & goto :fail )

rem ---------- 5. Где стоит программа сейчас ----------
echo [4/5] Ищу установленную версию...
set "INST="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; foreach($r in 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'){ $p=Join-Path $r '%APPID%'; if(Test-Path -LiteralPath $p){ (Get-ItemProperty -LiteralPath $p).InstallLocation.TrimEnd('\'); break } }"`) do set "INST=%%I"

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"

echo       Закрываю программу, если она открыта...
taskkill /IM LegalHelper.exe /F >nul 2>&1
taskkill /IM PDFMaster.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul
rem сохраняю нынешнюю версию — её можно вернуть: «Справка → Вернуть предыдущую версию программы»
set "CUR="
if defined INST set "CUR=!INST!"
if not defined CUR if exist "%PORTABLE%\LegalHelper.exe" set "CUR=%PORTABLE%"
if not defined CUR if exist "%OLDPORTABLE%\PDFMaster.exe" set "CUR=%OLDPORTABLE%"
if defined CUR (
    echo       Сохраняю предыдущую версию для возможного отката...
    robocopy "!CUR!" "%WORK%\previous" /MIR /XF unins*.* /R:1 /W:1 /NFL /NDL /NJH /NJS /NP >nul
)

echo [5/5] Устанавливаю...
if defined ISCC goto :via_installer
if defined INST goto :via_copy_inst
goto :via_portable

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
set "SETUP=%BSRC%\installer_output\LegalHelper_Setup.exe"
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
if not exist "!TARGET!\LegalHelper.exe" ( echo Не удалось скопировать программу в !TARGET! & goto :fail )
goto :done

:via_portable
set "TARGET=%PORTABLE%"
robocopy "!DIST!" "!TARGET!" /MIR /R:3 /W:2 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 ( echo Не удалось скопировать программу в !TARGET! & goto :fail )
if exist "%OLDPORTABLE%\PDFMaster.exe" rd /s /q "%OLDPORTABLE%"
rem ярлыки: рабочий стол и меню «Пуск» (старый ярлык с тем же именем заменяется)
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; foreach($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))){ $s=$ws.CreateShortcut((Join-Path $d 'LegalHelper.lnk')); $s.TargetPath='!TARGET!\LegalHelper.exe'; $s.WorkingDirectory='!TARGET!'; $s.IconLocation='!TARGET!\LegalHelper.exe,0'; $s.Save() }"
goto :done

:done
rem старые ярлыки «PDF Мастер» (на PDFMaster.exe) переводятся на LegalHelper.exe или удаляются, если новый уже есть
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $exe='!TARGET!\LegalHelper.exe'; foreach($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('CommonDesktopDirectory'), [Environment]::GetFolderPath('CommonPrograms'))){ if(-not $d -or -not (Test-Path -LiteralPath $d)){ continue }; Get-ChildItem -LiteralPath $d -Filter *.lnk -Recurse -ErrorAction SilentlyContinue | ForEach-Object { try { $s=$ws.CreateShortcut($_.FullName); if($s.TargetPath -like '*\PDFMaster.exe'){ $new=Join-Path $_.DirectoryName 'LegalHelper.lnk'; if(Test-Path -LiteralPath $new){ Remove-Item -LiteralPath $_.FullName -ErrorAction Stop } else { $s.TargetPath=$exe; $s.WorkingDirectory='!TARGET!'; $s.IconLocation=$exe+',0'; $s.Save(); Rename-Item -LiteralPath $_.FullName -NewName 'LegalHelper.lnk' -ErrorAction Stop } } } catch {} } }" >nul 2>&1
echo.
echo ============================================
echo   Готово. Установлена версия %VER%
echo   Папка программы: !TARGET!
echo ============================================
rem ярлык на рабочем столе должен быть всегда (раньше мог пропасть при смене названия программы)
if exist "!TARGET!\LegalHelper.exe" powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $exe='!TARGET!\LegalHelper.exe'; $dirs=@([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('CommonDesktopDirectory')); $has=$false; foreach($d in $dirs){ if($d -and (Test-Path -LiteralPath (Join-Path $d 'LegalHelper.lnk'))){ $has=$true } }; if(-not $has){ $s=$ws.CreateShortcut((Join-Path $dirs[0] 'LegalHelper.lnk')); $s.TargetPath=$exe; $s.WorkingDirectory='!TARGET!'; $s.IconLocation=$exe+',0'; $s.Save() }" >nul 2>&1
rem обновить кэш значков Windows, чтобы у ярлыка сразу была новая иконка
ie4uinit.exe -show >nul 2>&1
if exist "!TARGET!\LegalHelper.exe" start "" "!TARGET!\LegalHelper.exe"
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
