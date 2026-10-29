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
CloseApplications=force
CloseApplicationsFilter=central-server.exe
RestartApplications=no
UninstallDisplayIcon={app}\central-server.exe
[Files]
Source: "..\..\dist\central-server\central-server.exe"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{group}\Central Server"; Filename: "{app}\central-server.exe"; WorkingDir: "{app}"
[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ServerExe: String;
  ResultCode: Integer;
begin
  Result := '';
  ServerExe := ExpandConstant('{app}\central-server.exe');
  if FileExists(ServerExe) and
     FileExists(ExpandConstant('{commonappdata}\Linker\CentralServer\manager.json')) then
  begin
    Log('Stopping the configured Central Server before replacing application files.');
    if not Exec(ServerExe, '--component stop', ExpandConstant('{app}'),
                SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Result := 'Cannot stop Central Server. Close the server and run Setup again using the Windows account that manages it.'
    else if ResultCode <> 0 then
      Result := 'Central Server could not stop safely. Open Central Server, choose Stop server, and resolve the error before retrying Setup.';
  end;
end;
// PostgreSQL 17 or 18 is a prerequisite. Data, settings and credentials are retained
// on uninstall. Setup stops the configured server before closing remaining app
// processes. Stop the managed server manually before uninstalling.
