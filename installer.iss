; Скрипт установщика Inno Setup 6 для «LegalHelper» (до версии 1.6 — «PDF Мастер»)
#define MyAppName "LegalHelper"
#ifndef MyAppVersion
  #define MyAppVersion "3.7.1"
#endif
#define MyAppExe "LegalHelper.exe"

[Setup]
AppId={{7C2E8F4A-3B1D-4E9A-9F21-5D6A0B8C4E11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=LegalHelper
DefaultDirName={autopf}\LegalHelper
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=LegalHelper_Setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; ставится в папку пользователя: без прав администратора и без лишних вопросов
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
DisableDirPage=yes
DisableReadyPage=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; Windows 10 версии 1809 и новее (раньше — непонятные ошибки при запуске; Inno Setup скажет это сам)
MinVersion=10.0.17763
CloseApplications=force
UsePreviousAppDir=yes
UsePreviousPrivileges=yes
VersionInfoVersion={#MyAppVersion}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "openwith"; Description: "Добавить «LegalHelper» в меню «Открыть с помощью» для PDF"; GroupDescription: "Интеграция:"

[InstallDelete]
; убрать библиотеки старой версии перед установкой новой
Type: filesandordirs; Name: "{app}\_internal"
; программа версий до 1.6 («PDF Мастер») и её ярлыки
Type: files; Name: "{app}\PDFMaster.exe"
Type: files; Name: "{autoprograms}\PDF Мастер.lnk"
Type: files; Name: "{autodesktop}\PDF Мастер.lnk"

[Files]
Source: "dist\LegalHelper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; «Открыть с помощью» старой версии (PDFMaster.exe)
Root: HKA; Subkey: "Software\Classes\Applications\PDFMaster.exe"; Flags: deletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExe}"" ""%1"""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "PDFMaster.pdf"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\PDFMaster.pdf"; ValueType: string; ValueData: "PDF-документ"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\PDFMaster.pdf\DefaultIcon"; ValueType: string; ValueData: "{app}\{#MyAppExe},0"; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\PDFMaster.pdf\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExe}"" ""%1"""; Tasks: openwith

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
; обновление из программы (тихая установка /SILENT) — сразу открыть программу снова
Filename: "{app}\{#MyAppExe}"; Flags: nowait; Check: WizardSilent
