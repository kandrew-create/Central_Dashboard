#define AppVersion "0.4.0"
[Setup]
AppId={{F120F919-0A43-4AB4-858E-79C2C851D214}
AppName=Linker Central Server
AppVersion={#AppVersion}
AppPublisher=Linker Enterprise Inc.
DefaultDirName={autopf}\Linker\Central Server
DefaultGroupName=Linker Central Server
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\installer
OutputBaseFilename=Linker-Central-Server-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\central-server.exe
[Files]
Source: "..\..\dist\central-server\central-server.exe"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\Central Server"; Filename: "{app}\central-server.exe"; WorkingDir: "{app}"
// PostgreSQL 17 is a prerequisite. Data, settings and credentials are retained
// on uninstall. Stop the managed server before updating or uninstalling.
