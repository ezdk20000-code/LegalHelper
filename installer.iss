\xef\xbb\xbf; Скрипт установщика Inno Setup 6 для «PDF Мастер»
#define MyAppName "PDF Мастер"
#ifndef MyAppVersion
  #define MyAppVersion "1.5"
#endif
#define MyAppExe "PDFMaster.exe"

[Setup]
AppId={{7C2E8F4A-3B1D-4E9A-9F21-5D6A0B8C4E11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=PDF Мастер
DefaultDirName={autopf}\PDFMaster
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=PDFMaster_Setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
UsePreviousAppDir=yes
UsePreviousPrivileges=yes
VersionInfoVersion={#MyAppVersion}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "openwith"; Description: "Добавить «PDF Мастер» в меню «Открыть с помощью» для PDF"; GroupDescription: "Интеграция:"

[InstallDelete]
; убрать библиотеки старой версии перед установкой новой
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\PDFMaster\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExe}"" ""%1"""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "PDFMaster.pdf"; ValueData: ""; Flags: uninsdeletevalue; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\PDFMaster.pdf"; ValueType: string; ValueData: "PDF-документ"; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\PDFMaster.pdf\DefaultIcon"; ValueType: string; ValueData: "{app}\{#MyAppExe},0"; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\PDFMaster.pdf\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExe}"" ""%1"""; Tasks: openwith

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
