#ifndef Channel
  #define Channel "staging"
#endif
#ifndef VersionString
  #define VersionString "1.0.0"
#endif
#ifndef PayloadDir
  #error "Pass /DPayloadDir=<absolute payload folder> to ISCC."
#endif
#ifndef DesktopExe
  #error "Pass /DDesktopExe=<absolute GUI executable> to ISCC."
#endif
#ifndef BrandIcon
  #error "Pass /DBrandIcon=<absolute WEAVE icon> to ISCC."
#endif

#if Channel == "staging"
  #define SetupBaseName "WEAVE-CBT-Staging-Desktop-Setup"
  #define ChannelLabel "Staging"
#else
  #if Channel == "production"
    #define SetupBaseName "WEAVE-CBT-Desktop-Setup"
    #define ChannelLabel "Production"
  #else
    #error "Unknown release channel."
  #endif
#endif

[Setup]
AppId=WEAVE-CBT-Desktop-{#Channel}
AppName=WEAVE CBT Desktop Manager ({#ChannelLabel})
AppVersion={#VersionString}
AppPublisher=WEAVE
AppPublisherURL=https://weavecloudspace.com
AppSupportURL=https://weavecloudspace.com
DefaultDirName={autopf}\WeaveCBT
DefaultGroupName=WEAVE CBT
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#SourcePath}\..\..\..\dist
OutputBaseFilename={#SetupBaseName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
SetupIconFile={#BrandIcon}
UninstallDisplayIcon={app}\WEAVE-CBT-Desktop.exe
CloseApplications=ask
RestartApplications=no
AlwaysRestart=no
ChangesEnvironment=yes
AllowNoIcons=no
UsePreviousAppDir=no
VersionInfoDescription=WEAVE CBT Desktop Manager Setup
VersionInfoProductName=WEAVE CBT Desktop Manager
VersionInfoProductVersion={#VersionString}

[Files]
; Both binaries are bundled in this one setup EXE. No ZIP or CLI download is
; required on the school computer, including when internet is unavailable.
Source: "{#PayloadDir}\weave.exe"; DestDir: "{app}"; Flags: ignoreversion uninsneveruninstall
Source: "{#DesktopExe}"; DestDir: "{app}"; DestName: "WEAVE-CBT-Desktop.exe"; Flags: ignoreversion
Source: "{#PayloadDir}\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs uninsneveruninstall

[Registry]
; Makes the CLI available in a new terminal. Never remove an existing PATH
; entry, and leave the CLI available when only the desktop app is uninstalled.
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsPathEntry; Flags: preservestringtype

[Icons]
Name: "{autoprograms}\WEAVE CBT Desktop Manager"; Filename: "{app}\WEAVE-CBT-Desktop.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\WEAVE CBT Desktop Manager"; Filename: "{app}\WEAVE-CBT-Desktop.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
; The service itself remains managed by the CLI. Launch the desktop app under
; the ORIGINAL unelevated user token after completing the elevated setup.
Filename: "{app}\WEAVE-CBT-Desktop.exe"; Description: "Launch WEAVE CBT Desktop Manager"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
var
  CheckPage: TWizardPage;
  ManagerStatus: TNewStaticText;
  ServerStatus: TNewStaticText;
  ChannelStatus: TNewStaticText;

function NeedsPathEntry(): Boolean;
var
  ExistingPath: String;
  Needle: String;
begin
  if not RegQueryStringValue(HKLM, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', ExistingPath) then
  begin
    Result := True;
    Exit;
  end;
  Needle := ';' + Uppercase(ExpandConstant('{app}')) + ';';
  Result := Pos(Needle, ';' + Uppercase(ExistingPath) + ';') = 0;
end;

function ExistingManifest(): String;
var
  ManifestPath: String;
begin
  ManifestPath := ExpandConstant('{autopf}\WeaveCBT\assets\release-manifest.json');
  Result := '';
  if FileExists(ManifestPath) then
    LoadStringFromFile(ManifestPath, Result);
end;

function InitializeSetup(): Boolean;
var
  Manifest: String;
begin
  Result := True;
  Manifest := ExistingManifest();
  if FileExists(ExpandConstant('{autopf}\WeaveCBT\weave.exe')) and (Manifest = '') then
  begin
    MsgBox('An existing WEAVE CLI was found without a verifiable release manifest. Setup will not overwrite an unknown installation. Please repair the existing CLI installation first.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  if (Manifest <> '') and
      (Pos('"channel": "staging"', Manifest) > 0) and ('{#Channel}' <> 'staging') then
  begin
    MsgBox('A WEAVE CBT staging manager is installed. Remove it before installing production. Existing examination data will not be deleted.', mbError, MB_OK);
    Result := False;
  end;
  if (Manifest <> '') and
      (Pos('"channel": "production"', Manifest) > 0) and ('{#Channel}' <> 'production') then
  begin
    MsgBox('A WEAVE CBT production manager is installed. The staging installer cannot replace it.', mbError, MB_OK);
    Result := False;
  end;
end;

procedure InitializeWizard();
var
  Intro: TNewStaticText;
begin
  CheckPage := CreateCustomPage(
    wpWelcome, 'System readiness',
    'WEAVE checks this computer before installing the Desktop Manager.');

  Intro := TNewStaticText.Create(CheckPage);
  Intro.Parent := CheckPage.Surface;
  Intro.Left := ScaleX(0);
  Intro.Top := ScaleY(8);
  Intro.Width := CheckPage.SurfaceWidth;
  Intro.AutoSize := False;
  Intro.WordWrap := True;
  Intro.Height := ScaleY(56);
  Intro.Caption := 'The installer includes the matching WEAVE command-line manager and graphical dashboard. It will not install or alter the CBT server or examination data.';

  ManagerStatus := TNewStaticText.Create(CheckPage);
  ManagerStatus.Parent := CheckPage.Surface;
  ManagerStatus.Left := ScaleX(0);
  ManagerStatus.Top := ScaleY(82);
  ManagerStatus.Width := CheckPage.SurfaceWidth;
  ManagerStatus.AutoSize := False;
  ManagerStatus.WordWrap := True;
  ManagerStatus.Height := ScaleY(45);

  ServerStatus := TNewStaticText.Create(CheckPage);
  ServerStatus.Parent := CheckPage.Surface;
  ServerStatus.Left := ScaleX(0);
  ServerStatus.Top := ScaleY(134);
  ServerStatus.Width := CheckPage.SurfaceWidth;
  ServerStatus.AutoSize := False;
  ServerStatus.WordWrap := True;
  ServerStatus.Height := ScaleY(48);

  ChannelStatus := TNewStaticText.Create(CheckPage);
  ChannelStatus.Parent := CheckPage.Surface;
  ChannelStatus.Left := ScaleX(0);
  ChannelStatus.Top := ScaleY(194);
  ChannelStatus.Width := CheckPage.SurfaceWidth;
  ChannelStatus.AutoSize := False;
  ChannelStatus.WordWrap := True;
  ChannelStatus.Height := ScaleY(42);
end;

procedure CurPageChanged(CurPageID: Integer);
var
  ManagerPath: String;
begin
  if CurPageID <> CheckPage.ID then
    Exit;

  ManagerPath := ExpandConstant('{autopf}\WeaveCBT\weave.exe');
  if FileExists(ManagerPath) then
    ManagerStatus.Caption :=
      'CLI MANAGER: Found an existing WEAVE CLI. Setup will safely install the matching release in the same location.'
  else
    ManagerStatus.Caption :=
      'CLI MANAGER: Not installed. Setup will install the WEAVE CLI automatically.';

  if FileExists(ExpandConstant('{commonappdata}\WeaveCBT\install.json')) then
    ServerStatus.Caption :=
      'CBT SERVER: Existing installation detected. Server configuration, databases and examination records will be preserved.'
  else
    ServerStatus.Caption :=
      'CBT SERVER: Not installed. After setup, use the Install WEAVE CBT button in the manager.';

  ChannelStatus.Caption :=
    'RELEASE: {#ChannelLabel} {#VersionString}. Installation does not require manual ZIP extraction.';
end;
