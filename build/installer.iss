; Instalador de LOT Bot para Windows (Inno Setup 6).
;
;   iscc /DAppVersion=1.2.3 build\installer.iss
;
; - Se instala para el usuario (sin permisos de administrador) en
;   %LOCALAPPDATA%\Programs\LOT Bot.
; - Los datos del cliente (cuentas, anuncios, fotos, ajustes) viven aparte, en
;   %LOCALAPPDATA%\LOT Bot: ni instalar, ni actualizar, ni desinstalar los toca.
; - Actualizar = volver a ejecutar el instalador nuevo: LOT Bot lo hace solo en
;   modo silencioso (/SILENT) y al terminar se vuelve a abrir.
; - /NOLAUNCH: no abrir LOT Bot al terminar (lo usa la prueba automatica).
; Este fichero es ASCII a proposito (Inno Setup lo lee como ANSI).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F0D6C4B-2E7A-4B8E-9A6D-1C3F5E7A9B21}
AppName=LOT Bot
AppVersion={#AppVersion}
AppVerName=LOT Bot {#AppVersion}
AppPublisher=LOT
AppPublisherURL=https://www.lotbot.es
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\LOT Bot
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=LOT-Bot-Setup-{#AppVersion}
SetupIconFile=..\lot_bot\resources\lot_bot.ico
UninstallDisplayIcon={app}\LOT-Bot.exe
UninstallDisplayName=LOT Bot
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"

[InstallDelete]
; Al actualizar se quitan las librerias de la version anterior (no los datos).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\LOT-Bot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\LOT Bot"; Filename: "{app}\LOT-Bot.exe"
Name: "{autodesktop}\LOT Bot"; Filename: "{app}\LOT-Bot.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LOT-Bot.exe"; Description: "Abrir LOT Bot"; Flags: nowait postinstall; Check: ShouldLaunch

[Code]
function ShouldLaunch: Boolean;
begin
  Result := Pos('/NOLAUNCH', UpperCase(GetCmdTail)) = 0;
end;
