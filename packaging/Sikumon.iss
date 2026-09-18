#ifndef AppVersion
  #error AppVersion must be supplied by packaging/build.ps1
#endif

#define AppName "Sikumon"
#define AppExeName "Sikumon.exe"

[Setup]
AppId={{1B4D0D7A-9295-4E16-AB58-D893D680A628}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=SikumonSetup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription=Sikumon installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\Sikumon\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Sikumon"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\Sikumon"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Sikumon"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Intentionally empty: %LOCALAPPDATA%\Sikumon contains user meetings, models, DB,
; logs and credentials metadata and is preserved across uninstall/reinstall.
