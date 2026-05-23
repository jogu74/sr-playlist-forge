[Setup]
AppId={{D2C1C3B4-9E3D-4F2D-9A67-5C8B6F52E5A1}
AppName=SR Playlist Forge
AppVersion=2.5
AppVerName=SR Playlist Forge 2.5
AppPublisher=jogu74
DefaultDirName={autopf}\SR Playlist Forge
DefaultGroupName=SR Playlist Forge
DisableProgramGroupPage=yes
OutputDir=E:\Codex\SR Playlist Forge\release\installer
OutputBaseFilename=SR Playlist Forge 2.5 setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=E:\Codex\SR Playlist Forge\assets\icon.ico
UninstallDisplayIcon={app}\SR Playlist Forge.exe
VersionInfoVersion=2.5.0.0
VersionInfoTextVersion=2.5
VersionInfoCompany=jogu74
VersionInfoDescription=SR Playlist Forge 2.5 Installer
VersionInfoProductName=SR Playlist Forge
VersionInfoProductVersion=2.5

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "E:\Codex\SR Playlist Forge\release\windows\SR Playlist Forge.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\SR Playlist Forge"; Filename: "{app}\SR Playlist Forge.exe"
Name: "{autodesktop}\SR Playlist Forge"; Filename: "{app}\SR Playlist Forge.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SR Playlist Forge.exe"; Description: "Launch SR Playlist Forge"; Flags: nowait postinstall skipifsilent
