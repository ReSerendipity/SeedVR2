; launcher/installer.iss — SeedVR2 桌面安装包
; 编译：ISCC.exe launcher/installer.iss
; 注意：便携 Python 必须已预装小依赖（见 Task 9），torch 家族首启由启动器安装。

#define AppName "SeedVR2"
#define AppVersion "1.0.0"
#define AppPublisher "ReSerendipity"
#define AppExeName "SeedVR2.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\SeedVR2-lite
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=SeedVR2-Setup-{#AppVersion}
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
; 安装完成后自动启动启动器（首次引导）
[Run]
Filename: "{app}\{#AppExeName}"; Description: "立即启动 SeedVR2"; Flags: nowait postinstall skipifsilent

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: checkedonce

[Files]
; 应用本体（保持项目根结构，安装后 cwd=安装目录）
Source: "..\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs
Source: "..\common\*"; DestDir: "{app}\common"; Flags: recursesubdirs
Source: "..\model_lib\*"; DestDir: "{app}\model_lib"; Flags: recursesubdirs
Source: "..\configs_3b\*"; DestDir: "{app}\configs_3b"; Flags: recursesubdirs
Source: "..\configs_7b\*"; DestDir: "{app}\configs_7b"; Flags: recursesubdirs
Source: "..\config.yaml"; DestDir: "{app}"
Source: "..\.env.example"; DestDir: "{app}"
Source: "..\requirements.txt"; DestDir: "{app}"
; 便携 Python（已预装小依赖）
Source: "..\WPy64-312101\*"; DestDir: "{app}\WPy64-312101"; Flags: recursesubdirs
; 启动器（PyInstaller 产物，含引导页静态资源）
Source: "..\dist\SeedVR2.exe"; DestDir: "{app}"
; 冒烟测试图
Source: "..\demo\assets\inputs\input-1.jpg"; DestDir: "{app}\launcher\test-assets"; DestName: "test-input.jpg"
; 目录占位（model/、data/、logs/）
[Dirs]
Name: "{app}\model"
Name: "{app}\data"
Name: "{app}\logs"
Name: "{app}\launcher"
