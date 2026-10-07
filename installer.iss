; 假装外国人翻译器 · Inno Setup 6 安装脚本
; 编译: ISCC.exe installer.iss      （本文件必须存成 UTF-8 with BOM，否则中文会乱）

#define AppName        "假装外国人翻译器"
#define AppNameEn      "Pretend Foreigner Translator"
#define AppVer         "1.0.2"
#define AppPublisher   "NeoHotaru"
#define AppURL         "https://github.com/NeoHotaru"
#define SrcDir         "dist\pretend-foreigner"

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

; 配置和会话放在 %APPDATA%\pretend-foreigner\ —— 卸载时【不】动它们，
; 用户重装后设置还在。要彻底清干净就手删那个目录。
