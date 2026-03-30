; COM-IP Bridge 설치 스크립트 (Inno Setup)
; 제작: BurgerPark
; Inno Setup 다운로드: https://jrsoftware.org/isdl.php

#define MyAppName "COM-IP Bridge"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "BurgerPark"
#define MyAppExeName "ComIpBridge.exe"
#define MyAppDescription "BurgerPark 멀티포트 COM-IP 브릿지"

[Setup]
AppId={{B8A1C3D5-E7F9-4A2B-8C6D-1E3F5A7B9D0E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=Output
OutputBaseFilename=ComIpBridge_Setup_v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}
; SetupIconFile=..\src\Resources\app.ico    ; Uncomment when icon is available
LicenseFile=license.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Start with Windows (run at startup)"; GroupDescription: "System:"
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode

[Files]
; Published output files (self-contained single file)
Source: "..\publish\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--minimized"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Registry]
; File association for .combridge config files
Root: HKCR; Subkey: ".combridge"; ValueType: string; ValueName: ""; ValueData: "ComIpBridge.Config"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "ComIpBridge.Config"; ValueType: string; ValueName: ""; ValueData: "COM-IP Bridge Configuration"; Flags: uninsdeletekey
Root: HKCR; Subkey: "ComIpBridge.Config\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Post-install actions if needed
  end;
end;
