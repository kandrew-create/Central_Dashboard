#ifndef PackageSource
  #error Build with deploy/wsl/build-installer.ps1
#endif

[Setup]
AppId={{B6B0190A-EDCC-4AB8-97AF-D7DE3A7C294B}
AppName=Linker Central Server - WSL Docker
AppVersion={#PackageVersion}
AppPublisher=Linker
DefaultDirName={localappdata}\Programs\Linker\Central Server WSL Docker
DefaultGroupName=Linker Central Server - WSL Docker
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22631
OutputDir={#PackageOutput}
OutputBaseFilename=Linker-Central-Server-WSL-Docker-Setup-{#PackageVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayName=Linker Central Server - WSL Docker (Windows launcher)
UninstallDisplayIcon={app}\linker-wsl-setup.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Files]
Source: "{#PackageSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Finish WSL Docker Setup"; Filename: "{app}\linker-wsl-setup.exe"; WorkingDir: "{app}"
Name: "{group}\Central Server GUI"; Filename: "{app}\linker-wsl-setup.exe"; Parameters: "--launch"; WorkingDir: "{app}"

[Run]
Filename: "{app}\linker-wsl-setup.exe"; Description: "Set up WSL, Docker and the Central Server"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
    WizardForm.FinishedLabel.Caption := 'The Windows setup launcher is installed. Continue in the setup wizard to prepare Ubuntu, Docker and the server. Internet access is required. Uninstalling this launcher preserves your Linux application, credentials and Docker database volumes.';
end;
