; Inno Setup installer skeleton for the offline full installer.
; Build after creating dist\AISingingVideo and preparing runtime files.

#define MyAppName "AI Singing Video"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "AI Singing Video"
#define MyAppExeName "AISingingVideo.exe"

[Setup]
AppId={{0A0FA3D7-5A94-4304-9A25-AF61E63C5F7D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\AISingingVideo
DefaultGroupName={#MyAppName}
OutputDir=..\installer_output
OutputBaseFilename=AISingingVideoSetup-0.1.0
Compression=lzma2/fast
SolidCompression=no
DiskSpanning=yes
DiskSliceSize=2000000000
WizardStyle=modern

[Files]
Source: "..\dist\AISingingVideo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\singing_app\*"; DestDir: "{app}\singing_app"; Excludes: "projects\*,voice_library.json,__pycache__\*,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\tools\ApplioV3.6.2\*"; DestDir: "{app}\tools\ApplioV3.6.2"; Excludes: "__pycache__\*,*.pyc,logs\*,*.log,tests\*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\voice_pipeline\Generated_image*.png"; DestDir: "{app}\voice_pipeline"; Flags: ignoreversion
Source: "..\voice_pipeline\models\pomao_clear_voice_10e_1350s.pth"; DestDir: "{app}\voice_pipeline\models"; Flags: ignoreversion
Source: "..\voice_pipeline\models\pomao_clear_voice.index"; DestDir: "{app}\voice_pipeline\models"; Flags: ignoreversion
Source: "..\run_singing_app.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\run_singing_web.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\check_singing_app_runtime.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\USER_GUIDE_zh.md"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\singing_app\projects"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} Web UI"; Filename: "{app}\run_singing_web.bat"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\check_singing_app_runtime.bat"; Description: "Check runtime after install"; Flags: postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

