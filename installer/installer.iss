; File: installer/installer.iss
; Inno Setup script. Usage: iscc installer\installer.iss   (after pyinstaller) -> installer\Output\Mithra_WireGuard_Manager_Setup_<version>.exe
; Installs per user by default (no administrator rights needed); the app itself never needs them.
; Edit with: vi installer/installer.iss
#define AppVer Trim(FileRead(FileOpen("..\VERSION")))
[Setup]
AppId={{6B0E3C1D-6C55-4C1B-9A57-5F2D3E8A9C41}
AppName=Mithra WireGuard Manager
AppVerName=Mithra WireGuard Manager
UninstallDisplayName=Mithra WireGuard Manager
AppVersion={#AppVer}
AppPublisher=MithraCorp
AppPublisherURL=https://mithracorp.com
DefaultDirName={autopf}\MithraWireGuard
DefaultGroupName=Mithra WireGuard Manager
CloseApplications=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputBaseFilename=Mithra_WireGuard_Manager_Setup_{#AppVer}
SetupIconFile=..\assets\mithracorp_logo.ico
UninstallDisplayIcon={app}\MithraWireGuard.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
[Files]
Source: "..\dist\MithraWireGuard\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
[Icons]
Name: "{group}\Mithra WireGuard Manager"; Filename: "{app}\MithraWireGuard.exe"
Name: "{autodesktop}\Mithra WireGuard Manager"; Filename: "{app}\MithraWireGuard.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\MithraWireGuard.exe"; Description: "Start Mithra WireGuard Manager"; Flags: nowait postinstall skipifsilent
[Code]
{ Usage: runs by itself after the files are removed; asks once whether the saved servers, keys and settings go too (default: keep) }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if MsgBox('Also delete your saved servers, key configs and settings?' + #13#10 +
              'Choose No to keep them for a later install.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{localappdata}\MithraWireGuard'), True, True, True);
end;
