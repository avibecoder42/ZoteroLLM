"""Hilfsfunktionen für den Build: Versionsinfo, Lizenzen, Prüfsummen, Update-Manifest.

Aufruf: python packaging/build_tools.py version|licenses <Ordner>|manifest <Installer> [Basis-URL]|print-version
                                        |release-notes <Datei>
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from zotivity import __version__  # noqa: E402

PACKAGES = ["fastapi", "starlette", "pydantic", "pydantic_core", "uvicorn", "httpx", "httpcore", "h11", "anyio",
            "keyring", "pywin32-ctypes", "platformdirs", "numpy", "PyMuPDF", "openai", "anthropic", "google-genai",
            "google-auth", "pywebview", "pythonnet", "clr_loader", "proxy_tools", "bottle", "certifi", "idna",
            "sniffio", "distro", "jiter", "typing_extensions", "websockets", "tenacity", "requests", "urllib3",
            "charset-normalizer", "mcp", "pyinstaller"]


def version_info() -> None:
    parts = (__version__.split(".") + ["0", "0", "0"])[:4]
    nums = ", ".join(str(int("".join(c for c in p if c.isdigit()) or 0)) for p in parts)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({nums}), prodvers=({nums}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040704B0', [
      StringStruct('CompanyName', 'Zotivity'),
      StringStruct('FileDescription', 'Zotivity – Fragen und Forschungsstand für die Zotero-Bibliothek'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'Zotivity'),
      StringStruct('OriginalFilename', 'Zotivity.exe'),
      StringStruct('ProductName', 'Zotivity'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [0x0407, 1200])])
  ]
)
"""
    out = ROOT / "build" / "version_info.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(out)


def licenses(target: str) -> None:
    dest = Path(target) / "licenses"
    dest.mkdir(parents=True, exist_ok=True)
    lines = ["Drittanbieter-Komponenten / Third-party components", ""]
    for name in PACKAGES:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        lic = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
        lines.append(f"{dist.metadata['Name']} {dist.version}: {lic.splitlines()[0] if lic else 'siehe Lizenzdatei'}")
        folder = dest / dist.metadata["Name"]
        for file in dist.files or []:
            fname = str(file).lower()
            if any(key in fname for key in ("license", "copying", "notice")) and not fname.endswith((".py", ".pyc")):
                src = Path(dist.locate_file(file))
                if src.is_file() and src.stat().st_size < 2_000_000:
                    folder.mkdir(exist_ok=True)
                    shutil.copy2(src, folder / src.name)
    llama = ROOT / "build" / "vendor" / "llama"
    llama_build = (llama / "BUILD.txt").read_text(encoding="utf-8").strip() if (llama / "BUILD.txt").exists() else "?"
    if llama.exists():
        folder = dest / "llama.cpp"
        folder.mkdir(exist_ok=True)
        for name in ("LICENSE-llama.cpp", "LICENSE-LLVM-OpenMP"):
            if (llama / name).exists():
                shutil.copy2(llama / name, folder / name)
    lines += ["", "Python " + sys.version.split()[0] + ": PSF License",
              "PyMuPDF / MuPDF: AGPL-3.0 (Quellcode: https://github.com/pymupdf/PyMuPDF)",
              f"llama.cpp {llama_build} (eingebaute Embedding-Laufzeit): MIT (https://github.com/ggml-org/llama.cpp)",
              "LLVM OpenMP (libomp, Teil von llama.cpp): Apache-2.0 WITH LLVM-exception",
              "citeproc-js 2.4.63 (Vorschau im CSL-Editor): CPAL-1.0 oder AGPL-3.0 "
              "(https://github.com/Juris-M/citeproc-js; Lizenztext in _internal/zotivity/server/static/vendor/citeproc)",
              "CSL-Sprachdateien (citation-style-language/locales): CC BY-SA 3.0",
              "Microsoft Edge WebView2: Laufzeit von Microsoft (in Windows 10/11 enthalten)",
              "Embedding-Modelle werden nicht mitgeliefert; sie stehen unter den Lizenzen ihrer Hersteller "
              "(siehe Modellkatalog in den Einstellungen)."]
    (dest / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(dest)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(installer: str, base_url: str = "") -> None:
    path = Path(installer)
    data = {
        "version": __version__,
        "url": (base_url.rstrip("/") + "/" + path.name) if base_url else path.name,
        "sha256": sha256(path),
        "notes": "Zotivity " + __version__,
    }
    out = path.parent / "zotivity-update.json"
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    (path.parent / (path.name + ".sha256")).write_text(f"{data['sha256']}  {path.name}\n", encoding="utf-8")
    print(out)


def release_notes(target: str) -> None:
    """Release-Notes für GitHub: Abschnitt dieser Version aus CHANGELOG.md plus packaging/release-footer.md."""
    section: list[str] = []
    inside = False
    for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].split()[0] == __version__
            continue
        if inside:
            # Umbrochene Fortsetzungszeilen zusammenfügen: Auf Release-Seiten wird jeder Zeilenumbruch sichtbar
            if line.startswith("  ") and not line.lstrip().startswith("- ") and section and section[-1].strip():
                section[-1] += " " + line.strip()
            else:
                section.append(line)
    if not section:
        raise SystemExit(f"CHANGELOG.md enthält keinen Abschnitt für {__version__}")
    footer = (ROOT / "packaging" / "release-footer.md").read_text(encoding="utf-8").replace("{version}", __version__)
    Path(target).write_text("\n".join(section).strip() + "\n\n" + footer, encoding="utf-8")
    print(target)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "version":
        version_info()
    elif cmd == "licenses":
        licenses(sys.argv[2])
    elif cmd == "manifest":
        manifest(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    elif cmd == "print-version":
        print(__version__)
    elif cmd == "release-notes":
        release_notes(sys.argv[2])
