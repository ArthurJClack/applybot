; ApplyBot Windows installer (Inno Setup 6.3+). Built by build_installer.ps1, which passes /DAppVersion=x.y.z.
; Installs per-user by default (no admin prompt); Program Files is offered if launched elevated.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C0F2A4E-7D31-4B7A-9E5C-2B6A1F0D9C44}
AppName=ApplyBot
AppVersion={#AppVersion}
AppVerName=ApplyBot {#AppVersion}
AppPublisher=Arthur Clack
DefaultDirName={autopf}\ApplyBot
DefaultGroupName=ApplyBot
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
SetupIconFile=assets\ApplyBot.ico
UninstallDisplayIcon={app}\ApplyBot.exe
UninstallDisplayName=ApplyBot
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
OutputDir=dist
OutputBaseFilename=ApplyBot-Setup-{#AppVersion}
; your profile, answers and history live in Documents\ApplyBot and are never touched by install/uninstall

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\ApplyBot.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\ApplyBot"; Filename: "{app}\ApplyBot.exe"
Name: "{autodesktop}\ApplyBot"; Filename: "{app}\ApplyBot.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ApplyBot.exe"; Description: "{cm:LaunchProgram,ApplyBot}"; Flags: nowait postinstall skipifsilent
