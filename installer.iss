; 假装外国人翻译器 · Inno Setup 6 安装脚本
; 编译: ISCC.exe installer.iss      （本文件必须存成 UTF-8 with BOM，否则中文会乱）

#define AppName        "假装外国人翻译器"
#define AppNameEn      "Pretend Foreigner Translator"
#define AppVer         "1.1.1"
#define AppPublisher   "NeoHotaru"
#define AppURL         "https://github.com/NeoHotaru"
#ifndef SrcDir
#define SrcDir         "dist\pretend-foreigner"
#endif

[Setup]
AppId={{8E1C2A54-3B7D-4F6E-9A11-7C5D2E4B9F30}
AppName={#AppName}
AppVersion={#AppVer}
AppVerName={#AppName} {#AppVer}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={localappdata}\Programs\pretend-foreigner
DisableDirPage=no
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=pretend-foreigner-setup-{#AppVer}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\app-icon.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\pretend-foreigner.exe
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\pretend-foreigner.exe"
Name: "{group}\Uninstall {#AppNameEn}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\pretend-foreigner.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\pretend-foreigner.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\pretend-foreigner.exe"; Flags: nowait; Check: IsAutomaticUpdate

; 配置和会话放在 %APPDATA%\pretend-foreigner\ —— 卸载时【不】动它们，
; 用户重装后设置还在。要彻底清干净就手删那个目录。

[Code]
function OpenProcess(Access: LongWord; Inherit: Boolean; ProcessId: LongWord): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(Handle: THandle; Milliseconds: LongWord): LongWord;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

function ProcessLastError: LongWord;
  external 'GetLastError@kernel32.dll stdcall';

function IsAutomaticUpdate: Boolean;
begin
  Result := ExpandConstant('{param:PFTUPDATE|0}') = '1';
end;

function InitializeSetup: Boolean;
var
  ParentId: Integer;
  ParentHandle: THandle;
  WaitResult: LongWord;
begin
  Result := True;
  if not IsAutomaticUpdate then exit;
  ParentId := StrToIntDef(ExpandConstant('{param:PFTPID|0}'), 0);
  if ParentId <= 0 then begin
    Log('Update cancelled: missing parent process id');
    Result := False;
    exit;
  end;
  ParentHandle := OpenProcess($00100000, False, ParentId);
  if ParentHandle = 0 then begin
    if ProcessLastError <> 87 then begin
      Log('Update cancelled: cannot wait for previous application');
      Result := False;
    end;
    exit;
  end;
  Log('Waiting for previous application to save data and exit');
  WaitResult := WaitForSingleObject(ParentHandle, 30000);
  CloseHandle(ParentHandle);
  if WaitResult <> 0 then begin
    Log('Update cancelled: previous application did not exit');
    Result := False;
  end;
end;