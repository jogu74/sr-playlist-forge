#define MyAppVersion "2.14.3"
#define ProjectRoot AddBackslash(SourcePath) + ".."

[Setup]
AppId={{D2C1C3B4-9E3D-4F2D-9A67-5C8B6F52E5A1}
AppName=SR Playlist Forge
AppVersion={#MyAppVersion}
AppVerName=SR Playlist Forge {#MyAppVersion}
AppPublisher=jogu74
DefaultDirName={autopf}\SR Playlist Forge
DefaultGroupName=SR Playlist Forge
DisableProgramGroupPage=yes
OutputDir={#SourcePath}installer
OutputBaseFilename=SR Playlist Forge {#MyAppVersion} setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile={#ProjectRoot}\assets\icon.ico
UninstallDisplayIcon={app}\SR Playlist Forge.exe
VersionInfoVersion={#MyAppVersion}.0
VersionInfoTextVersion={#MyAppVersion}
VersionInfoCompany=jogu74
VersionInfoDescription=SR Playlist Forge {#MyAppVersion} Installer
VersionInfoProductName=SR Playlist Forge
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#ProjectRoot}\release\windows\SR Playlist Forge.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\SR Playlist Forge"; Filename: "{app}\SR Playlist Forge.exe"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\SR Playlist Forge"; Filename: "{app}\SR Playlist Forge.exe"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\SR Playlist Forge.exe"; Description: "Launch SR Playlist Forge"; Flags: nowait postinstall skipifsilent
