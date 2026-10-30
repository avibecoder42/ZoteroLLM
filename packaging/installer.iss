; Inno-Setup-Skript für ZotLLM (Windows), aufgebaut wie bei LLMplot.
; Installation pro Benutzer ohne Adminrechte (optional für alle Benutzer). Updates: neue Version über
; die bestehende installieren (gleiche AppId) – das Setup erkennt die installierte Version und fragt nach.
; Die Update-Funktion im Programm startet das Setup unbeaufsichtigt (/SILENT) ohne Rückfrage.

#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppName "ZotLLM"
#define AppExe "ZotLLM.exe"
#define AppGuid "3937161B-2067-4851-A809-F02872C3B59E"
#define AppMutexName "ZotLLMRunningMutex"
; Früherer Name bis 0.7.3 – gleiche AppId, das Setup aktualisiert jene Installation
#define LegacyName "ZoteroLLM"
#define LegacyMutexName "ZoteroLLMRunningMutex"

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=ZotLLM
AppComments=Fragen und Forschungsstand für die eigene Zotero-Bibliothek
; Bisheriger Ordner wird beibehalten – ausser dem Standardordner des früheren Namens (siehe [Code]: AppDir)
DefaultDirName={code:AppDir}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
UsePreviousAppDir=no
UsePreviousLanguage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=ZotLLM-Setup-{#AppVersion}
SetupIconFile=zotllm.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Läuft ZotLLM (Fenster oder unsichtbar im Hintergrund, z. B. vom Zotero-Plugin gestartet), beendet das Setup
; es selbst über die lokale Schnittstelle (siehe [Code]: EnsureAppClosed) – statt nur „läuft noch“ zu melden.
; Kein AppMutex-Eintrag: dessen Prüfung käme vor dem Beenden und würde nur eine Meldung zeigen.
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}.0
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
MinVersion=10.0

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
de.UpdatePrompt=ZotLLM %1 ist bereits installiert.%n%nAuf Version %2 aktualisieren? Einstellungen, Index, Wissenskorpora und gespeicherte API-Schlüssel bleiben erhalten.
fr.UpdatePrompt=ZotLLM %1 est déjà installé.%n%nMettre à jour vers la version %2 ? Les paramètres, l'index, les corpus et les clés API enregistrées sont conservés.
it.UpdatePrompt=ZotLLM %1 è già installato.%n%nAggiornare alla versione %2? Impostazioni, indice, corpora e chiavi API salvate vengono mantenuti.
en.UpdatePrompt=ZotLLM %1 is already installed.%n%nUpdate to version %2? Settings, index, corpora and stored API keys are kept.
de.ReinstallPrompt=ZotLLM %1 ist bereits installiert.%n%nDieselbe Version erneut installieren (Reparatur)?
fr.ReinstallPrompt=ZotLLM %1 est déjà installé.%n%nRéinstaller la même version (réparation) ?
it.ReinstallPrompt=ZotLLM %1 è già installato.%n%nReinstallare la stessa versione (riparazione)?
en.ReinstallPrompt=ZotLLM %1 is already installed.%n%nReinstall the same version (repair)?
de.DowngradePrompt=Eine neuere Version (ZotLLM %1) ist installiert.%n%nTrotzdem die ältere Version %2 installieren?
fr.DowngradePrompt=Une version plus récente (ZotLLM %1) est installée.%n%nInstaller quand même l'ancienne version %2 ?
it.DowngradePrompt=È installata una versione più recente (ZotLLM %1).%n%nInstallare comunque la versione precedente %2?
en.DowngradePrompt=A newer version (ZotLLM %1) is installed.%n%nInstall the older version %2 anyway?
de.WebView2Missing=Für das Programmfenster wird die Microsoft-Edge-WebView2-Laufzeit benötigt. Sie ist in Windows 10 und 11 normalerweise vorhanden, wurde hier aber nicht gefunden.%n%nBitte nach der Installation von https://developer.microsoft.com/microsoft-edge/webview2/ installieren.
fr.WebView2Missing=Le runtime Microsoft Edge WebView2 est nécessaire mais introuvable.%n%nVeuillez l'installer depuis https://developer.microsoft.com/microsoft-edge/webview2/ après l'installation.
it.WebView2Missing=È necessario il runtime Microsoft Edge WebView2, che non è stato trovato.%n%nInstallarlo da https://developer.microsoft.com/microsoft-edge/webview2/ dopo l'installazione.
en.WebView2Missing=The Microsoft Edge WebView2 runtime is required but was not found.%n%nPlease install it from https://developer.microsoft.com/microsoft-edge/webview2/ after setup.
de.StillRunning=ZotLLM läuft noch und konnte nicht automatisch beendet werden.%n%nBitte ZotLLM schliessen (oder im Task-Manager beenden) und dann „Wiederholen“ wählen.
fr.StillRunning=ZotLLM est encore en cours d'exécution et n'a pas pu être fermé automatiquement.%n%nVeuillez fermer ZotLLM (ou le terminer dans le Gestionnaire des tâches), puis cliquer sur « Réessayer ».
it.StillRunning=ZotLLM è ancora in esecuzione e non è stato possibile chiuderlo automaticamente.%n%nChiudere ZotLLM (o terminarlo in Gestione attività) e poi scegliere «Riprova».
en.StillRunning=ZotLLM is still running and could not be closed automatically.%n%nPlease close ZotLLM (or end it in Task Manager), then choose "Retry".

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Programmdateien älterer Versionen entfernen, damit keine veralteten Bibliotheken zurückbleiben.
Type: filesandordirs; Name: "{app}\_internal"
; Verknüpfungen des früheren Namens (bis 0.7.3); dessen Programmordner entfernt [Code]: RemoveLegacyAppDir
Type: files; Name: "{autoprograms}\{#LegacyName}.lnk"
Type: files; Name: "{autodesktop}\{#LegacyName}.lnk"

[Files]
Source: "..\dist\ZotLLM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "ZotLLM.Desktop"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "ZotLLM.Desktop"; Tasks: desktopicon

[Run]
; Auch nach einem unbeaufsichtigten Update (Update-Funktion im Programm) wieder starten
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
; Einstellungen, Index und Schlüssel (Windows-Anmeldeinformationsverwaltung) bleiben bei der Deinstallation erhalten.

[Code]
// Ist bereits eine Version installiert, fragt das Setup nach (Update, Reparatur oder Rückstufung).
// Unbeaufsichtigte Installationen (/SILENT, aus der Update-Funktion) fragen nicht.
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppGuid}}_is1';
  WebView2Key = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function InstalledVersion(): String;
var
  Value: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', Value) then
    Result := Value
  else if IsWin64 and RegQueryStringValue(HKLM64, UninstallKey, 'DisplayVersion', Value) then
    Result := Value
  else if RegQueryStringValue(HKLM32, UninstallKey, 'DisplayVersion', Value) then
    Result := Value;
end;

var
  PreviousAppPath: String;

function InstalledAppPath(): String;
var
  Value: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, UninstallKey, 'Inno Setup: App Path', Value) then
    Result := Value
  else if IsWin64 and RegQueryStringValue(HKLM64, UninstallKey, 'Inno Setup: App Path', Value) then
    Result := Value
  else if RegQueryStringValue(HKLM32, UninstallKey, 'Inno Setup: App Path', Value) then
    Result := Value;
end;

// Zielordner: der bisherige – ausser er heisst noch wie früher (ZoteroLLM), dann daneben der neue Name
function AppDir(Param: String): String;
begin
  Result := RemoveBackslashUnlessRoot(PreviousAppPath);
  if Result = '' then
    Result := ExpandConstant('{autopf}\{#AppName}')
  else if CompareText(ExtractFileName(Result), '{#LegacyName}') = 0 then
    Result := ExtractFilePath(Result) + '{#AppName}';
end;

// Nach der Installation den Programmordner des früheren Namens entfernen (nur Programmdateien; Einstellungen,
// Index und Schlüssel liegen anderswo und übernimmt ZotLLM beim ersten Start)
procedure CurStepChanged(CurStep: TSetupStep);
var
  Legacy: String;
begin
  if CurStep <> ssPostInstall then
    Exit;
  Legacy := RemoveBackslashUnlessRoot(PreviousAppPath);
  if (Legacy <> '') and (CompareText(ExtractFileName(Legacy), '{#LegacyName}') = 0)
    and (CompareText(Legacy, RemoveBackslashUnlessRoot(ExpandConstant('{app}'))) <> 0)
    and FileExists(AddBackslash(Legacy) + '{#LegacyName}.exe') then
    DelTree(Legacy, True, True, True);
end;

function WebView2Installed(): Boolean;
var
  Value: String;
begin
  Result := (RegQueryStringValue(HKLM32, WebView2Key, 'pv', Value) and (Value <> '') and (Value <> '0.0.0.0'))
    or (IsWin64 and RegQueryStringValue(HKLM64, WebView2Key, 'pv', Value) and (Value <> '') and (Value <> '0.0.0.0'))
    or (RegQueryStringValue(HKCU, WebView2Key, 'pv', Value) and (Value <> '') and (Value <> '0.0.0.0'));
end;

// -- Laufende Instanz beenden ------------------------------------------------------------------------------
// ZotLLM hält den Mutex, solange es läuft (auch unsichtbar). Beendet wird es über seine lokale Schnittstelle
// (POST /api/shutdown mit dem Kopf X-ZotLLM) – Port aus %LOCALAPPDATA%\ZotLLM\service.json, sonst 23120.
// Die Version bis 0.7.3 (ZoteroLLM) hat eigenen Mutex, Ordner und Kopf.
function AppRunning(): Boolean;
begin
  Result := CheckForMutexes('{#AppMutexName},{#LegacyMutexName}');
end;

function ServicePort(): Integer;
var
  S: AnsiString;
  P, I: Integer;
  Num: String;
begin
  Result := 23120;
  if not LoadStringFromFile(ExpandConstant('{localappdata}\{#AppName}\service.json'), S)
    and not LoadStringFromFile(ExpandConstant('{localappdata}\{#LegacyName}\service.json'), S) then
    Exit;
  P := Pos('"port":', S);
  if P = 0 then
    Exit;
  I := P + 7;
  while (I <= Length(S)) and (S[I] = ' ') do
    I := I + 1;
  Num := '';
  while (I <= Length(S)) and (S[I] >= '0') and (S[I] <= '9') do
  begin
    Num := Num + S[I];
    I := I + 1;
  end;
  Result := StrToIntDef(Num, 23120);
end;

procedure StopRunningApp();
var
  Http: Variant;
  I: Integer;
begin
  if not AppRunning() then
    Exit;
  try
    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.SetTimeouts(2000, 2000, 3000, 5000);
    Http.Open('POST', 'http://127.0.0.1:' + IntToStr(ServicePort()) + '/api/shutdown', False);
    Http.SetRequestHeader('X-ZotLLM', '1');
    Http.SetRequestHeader('X-{#LegacyName}', '1');
    Http.SetRequestHeader('Content-Type', 'application/json');
    Http.Send('{}');
  except
    Log('ZotLLM antwortet nicht auf /api/shutdown: ' + GetExceptionMessage());
  end;
  // bis zu 15 Sekunden warten, bis der Prozess beendet ist
  for I := 1 to 60 do
  begin
    if not AppRunning() then
      Exit;
    Sleep(250);
  end;
end;

function EnsureAppClosed(): Boolean;
begin
  StopRunningApp();
  while AppRunning() do
  begin
    if MsgBox(CustomMessage('StillRunning'), mbError, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
    StopRunningApp();
  end;
  Result := True;
end;

function InitializeSetup(): Boolean;
var
  Installed, Prompt: String;
  OldVer, NewVer: Int64;
  Cmp: Integer;
begin
  Result := True;
  if not WizardSilent() and not WebView2Installed() then
    MsgBox(CustomMessage('WebView2Missing'), mbInformation, MB_OK);
  PreviousAppPath := InstalledAppPath();
  Installed := InstalledVersion();
  if (Installed <> '') and not WizardSilent() then
  begin
    Cmp := -1;
    if StrToVersion(Installed, OldVer) and StrToVersion('{#AppVersion}', NewVer) then
      Cmp := ComparePackedVersion(OldVer, NewVer);
    if Cmp < 0 then
      Prompt := FmtMessage(CustomMessage('UpdatePrompt'), [Installed, '{#AppVersion}'])
    else if Cmp = 0 then
      Prompt := FmtMessage(CustomMessage('ReinstallPrompt'), [Installed])
    else
      Prompt := FmtMessage(CustomMessage('DowngradePrompt'), [Installed, '{#AppVersion}']);
    Result := MsgBox(Prompt, mbConfirmation, MB_YESNO) = IDYES;
  end;
  if Result then
    Result := EnsureAppClosed();
end;

function InitializeUninstall(): Boolean;
begin
  Result := EnsureAppClosed();
end;
