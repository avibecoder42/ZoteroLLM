# PyInstaller-Spezifikation (Ordner-Build). Aufruf: python -m PyInstaller packaging/zotivity.spec
# Plattformen: Windows (EXE), macOS (.app über BUNDLE), Linux (Ordner, z. B. für AppImage).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from zotivity import __version__  # noqa: E402

datas = [
    (str(SRC / "zotivity" / "server" / "static"), "zotivity/server/static"),
    (str(SRC / "zotivity" / "plugin"), "zotivity/plugin"),
    # Modellkatalog und Testsatz für den Kurztest der Embedding-Modelle
    (str(SRC / "zotivity" / "data"), "zotivity/data"),
]
# Eingebaute Embedding-Laufzeit (packaging/fetch_llama.py); als Daten kopiert, damit PyInstaller die DLLs nicht anfasst
LLAMA = ROOT / "build" / "vendor" / "llama"
if sys.platform == "win32":
    if not (LLAMA / "llama-server.exe").exists():
        raise SystemExit("llama.cpp fehlt – zuerst packaging/fetch_llama.py ausführen")
    datas.append((str(LLAMA), "llama"))
datas += collect_data_files("certifi")
datas += collect_data_files("google.genai")
# Pakete, die zur Laufzeit ihre eigene Version oder Einstiegspunkte lesen
for dist in ("keyring", "google-genai", "anthropic", "openai", "httpx", "fastapi", "uvicorn", "pydantic", "pymupdf"):
    try:
        datas += copy_metadata(dist)
    except Exception:  # noqa: BLE001 - nicht installiert
        pass

hiddenimports = collect_submodules("zotivity")
# Modul „Recherche“: das Paket zotivity.research samt Quellen (sources/); collect_submodules("zotivity") erfasst es schon,
# ausdrücklich genannt, damit es auch bei einer engeren Auswahl nicht fehlt (Selbsttest prüft /api/research/…)
hiddenimports += collect_submodules("zotivity.research")
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += ["win32ctypes.core", "webview.platforms.winforms", "webview.platforms.edgechromium", "clr"]
try:
    hiddenimports += collect_submodules("mcp", filter=lambda name: not name.startswith("mcp.cli"))
except Exception:  # noqa: BLE001
    pass

excludes = ["tkinter", "_tkinter", "matplotlib", "pandas", "scipy", "IPython", "pytest", "torch", "sentence_transformers",
            "PyQt5", "PyQt6", "PySide2", "PySide6", "gi", "cefpython3"]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

manifest = None
if sys.platform == "win32":
    # DPI-bewusst (scharf bei 125/150 %) und lange Pfade erlaubt
    manifest = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false"></requestedExecutionLevel></requestedPrivileges></security>
  </trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application><supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"></supportedOS></application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
    </windowsSettings>
  </application>
</assembly>
"""

icon = str(ROOT / "packaging" / ("zotivity.icns" if sys.platform == "darwin" else "zotivity.ico"))
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Zotivity",
    console=False,
    icon=icon if Path(icon).exists() else None,
    version=str(ROOT / "build" / "version_info.txt") if sys.platform == "win32" else None,
    manifest=manifest,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Zotivity", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Zotivity.app",
        icon=icon if Path(icon).exists() else None,
        bundle_identifier="ch.zotivity.desktop",
        version=__version__,
        info_plist={"NSHighResolutionCapable": True},
    )
