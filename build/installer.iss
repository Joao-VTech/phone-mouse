; Instalador do Phone Mouse (Inno Setup 6). Gerado por build\build.py.
#define AppVer "1.1.0"
#define AppExe "PhoneMouse.exe"

[Setup]
AppId={{8C6E2C3A-5B7F-4E62-9C1E-2F1A7D4B9E01}
AppName=Phone Mouse
AppVersion={#AppVer}
AppVerName=Phone Mouse {#AppVer}
AppPublisher=JV Tech
AppPublisherURL=https://github.com/Joao-VTech/phone-mouse
AppSupportURL=https://github.com/Joao-VTech/phone-mouse/issues
AppUpdatesURL=https://github.com/Joao-VTech/phone-mouse/releases
; instala só para o usuário: não pede administrador
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Phone Mouse
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir=out
OutputBaseFilename=PhoneMouse-Setup-{#AppVer}
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName=Phone Mouse
LicenseFile=..\LICENSE
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=no

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
pt.TaskDesktop=Criar atalho na área de trabalho
en.TaskDesktop=Create a desktop shortcut
pt.TaskAutostart=Iniciar junto com o Windows
en.TaskAutostart=Start with Windows
pt.TaskAdmin=Modo administrador (para jogos e janelas de admin; o Windows pede permissão uma vez)
en.TaskAdmin=Admin mode (for games and admin windows; Windows asks for permission once)
pt.RunNow=Abrir o Phone Mouse agora
en.RunNow=Open Phone Mouse now

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktop}"
Name: "autostart"; Description: "{cm:TaskAutostart}"
Name: "admin"; Description: "{cm:TaskAdmin}"; Flags: unchecked

[Files]
Source: "out\dist\PhoneMouse\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Phone Mouse"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\Phone Mouse"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; ordem importa: o modo administrador refaz o atalho de inicialização para abrir já como admin
Filename: "{app}\{#AppExe}"; Parameters: "--autostart on"; Tasks: autostart; Flags: runhidden waituntilterminated
Filename: "{app}\{#AppExe}"; Parameters: "--install-admin"; Tasks: admin; Flags: waituntilterminated
Filename: "{app}\{#AppExe}"; Description: "{cm:RunNow}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\{#AppExe}"; Parameters: "--uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "PhoneMouseUninstall"

[Code]
// antes de copiar os arquivos (atualização), encerra o Phone Mouse que estiver rodando
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  if FileExists(ExpandConstant('{app}\{#AppExe}')) then
    Exec(ExpandConstant('{app}\{#AppExe}'), '--stop', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
