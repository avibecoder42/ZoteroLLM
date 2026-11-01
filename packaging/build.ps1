# Baut Zotivity für Windows: Tests, Symbole, PyInstaller-Ordner, Lizenzen, Selbsttest, Inno-Setup-Installer, Update-Manifest.
# Aufruf (PowerShell):  .\packaging\build.ps1                     (vollständig)
#                       .\packaging\build.ps1 -SkipTests          (ohne pytest)
#                       .\packaging\build.ps1 -UpdateBaseUrl https://…/zotivity   (Adresse für das Update-Manifest)
#                       .\packaging\build.ps1 -SkipWindowTest     (Selbsttest ohne Fenster, z. B. auf GitHub Actions)
param(
    [switch]$SkipTests,
    [switch]$SkipSelfTest,
    [switch]$SkipWindowTest,
    [string]$UpdateBaseUrl = ""
)
# "Continue": PyInstaller und pytest schreiben Protokolle nach stderr, was Windows PowerShell 5.1 bei umgeleiteter
# Ausgabe sonst als Fehler abbricht. Fehlschläge werden über $LASTEXITCODE erkannt.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Erstelle virtuelle Umgebung …"
    python -m venv (Join-Path $root ".venv")
    & $py -m pip install --upgrade pip
}
# Abhängigkeiten für den Build nur nachinstallieren, wenn sie fehlen (kein Netzzugriff bei vollständiger Umgebung)
& $py -c "import PyInstaller, webview, pytest" 2>$null
if ($LASTEXITCODE -ne 0) {
    # Mit den getesteten Versionen (constraints.txt): neuere Pakete brauchen u. U. Anpassungen am PyInstaller-Paket
    & $py -m pip install -c (Join-Path $PSScriptRoot "constraints.txt") -e "$root[dev,build,mcp]"
    if ($LASTEXITCODE -ne 0) { throw "Installation der Abhängigkeiten fehlgeschlagen" }
}
New-Item -ItemType Directory -Force (Join-Path $root "build") | Out-Null
$version = (& $py (Join-Path $PSScriptRoot "build_tools.py") print-version).Trim()
Write-Host "Zotivity $version"

if (-not $SkipTests) {
    & $py -m pytest -q --basetemp (Join-Path $root "build\pytest") -p no:cacheprovider (Join-Path $root "tests")
    if ($LASTEXITCODE -ne 0) { throw "Tests fehlgeschlagen" }
}

& $py (Join-Path $PSScriptRoot "make_icons.py") | Out-Null
& $py (Join-Path $PSScriptRoot "build_tools.py") version | Out-Null
# Eingebaute Embedding-Laufzeit (llama.cpp, feste Version mit Prüfsumme; Modelle werden nicht mitgeliefert)
& $py (Join-Path $PSScriptRoot "fetch_llama.py")
if ($LASTEXITCODE -ne 0) { throw "llama.cpp konnte nicht bereitgestellt werden" }
& $py -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot "zotivity.spec") --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build\pyinstaller")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fehlgeschlagen" }
& $py (Join-Path $PSScriptRoot "build_tools.py") licenses (Join-Path $root "dist\Zotivity") | Out-Null

if (-not $SkipSelfTest) {
    $st = Join-Path $root "build\selftest"
    if (Test-Path $st) { Remove-Item -Recurse -Force $st }
    $exe = Join-Path $root "dist\Zotivity\Zotivity.exe"
    $stArgs = @("--self-test", "`"$st`"")
    if ($SkipWindowTest) { $stArgs += "--no-window" }
    $p = Start-Process -FilePath $exe -ArgumentList $stArgs -PassThru -Wait
    $json = Join-Path $st "selftest.json"
    if (-not (Test-Path $json)) { throw "Selbsttest abgestürzt (Exit-Code $($p.ExitCode)). Details: Ereignisanzeige, Windows-Protokolle, Anwendung" }
    $report = Get-Content $json -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($s in $report.steps) { Write-Host ("  {0,-32} {1}" -f $s.step, $(if ($s.ok) { "ok  $($s.detail)" } else { "FEHLER" })) }
    if ($report.errors.Count -gt 0) { throw "Selbsttest mit Fehlern: $($report.errors -join '; ')" }
    Write-Host "Selbsttest bestanden"
}

$iscc = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 (ISCC.exe) nicht gefunden. Installation: winget install JRSoftware.InnoSetup" }
& $iscc /Q "/DAppVersion=$version" (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup fehlgeschlagen" }
$installer = Join-Path $root "dist\Zotivity-Setup-$version.exe"
& $py (Join-Path $PSScriptRoot "build_tools.py") manifest $installer $UpdateBaseUrl | Out-Null
Write-Host "Fertig: $installer"
