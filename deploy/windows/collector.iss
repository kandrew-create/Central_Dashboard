#define AppVersion "0.4.0"
[Setup]
AppId={{C909F5ED-5147-4E05-9566-2E1D63576B16}
AppName=Linker SCADA Collector
AppVersion={#AppVersion}
AppPublisher=Linker Enterprise Inc.
DefaultDirName={autopf}\Linker\SCADA Collector
DefaultGroupName=Linker SCADA Collector
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\installer
OutputBaseFilename=Linker-SCADA-Collector-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
UninstallDisplayIcon={app}\collector-gui.exe
[Files]
Source: "..\..\dist\collector\*.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\collector\config.example.toml"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\Collector"; Filename: "{app}\collector-gui.exe"; Parameters: "--config ""{commonappdata}\Linker\Collector\config.toml"""; WorkingDir: "{app}"
[UninstallRun]
Filename: "{app}\collector-admin.exe"; Parameters: "remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveCollectorService"
[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
// Configuration, credentials, queue and logs are deliberately not installer
// files. Uninstall retains them. Explicit deletion uses collector-admin remove
// --delete-state after review of pending work.
