"""Selbsttest des gebündelten Programms: ``Zotivity.exe --self-test <Ordner>``.

Prüft ohne Fenster und ohne die Daten der Nutzerin bzw. des Nutzers anzufassen, ob alle Teile im Paket
enthalten sind und laufen: Dienst (uvicorn/FastAPI), Oberfläche, Plugin-Dateien, PDF-Lesen (PyMuPDF),
Vektoren (NumPy), Schlüsselspeicher und die WebView2-Anbindung. Ergebnis: <Ordner>/selftest.json.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path


def run(out_dir: str) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # Eigener, leerer Datenordner – nie die echten Einstellungen oder den echten Index verwenden
    home = Path(tempfile.mkdtemp(prefix="zotivity-selftest-"))
    os.environ["ZOTIVITY_HOME"] = str(home)
    report: dict = {"steps": [], "errors": [], "frozen": bool(getattr(sys, "frozen", False)), "python": sys.version}

    def step(name, fn):
        t0 = time.time()
        try:
            detail = fn()
            report["steps"].append({"step": name, "ok": True, "seconds": round(time.time() - t0, 2), "detail": detail})
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"{name}: {e}")
            report["steps"].append({"step": name, "ok": False, "error": traceback.format_exc(limit=6)})

    def pdf():
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Selbsttest Zotivity: Kollaborative Dokumentation")
        data = doc.tobytes()
        text = pymupdf.open(stream=data, filetype="pdf")[0].get_text()
        assert "Kollaborative" in text, text
        return f"PyMuPDF {pymupdf.VersionBind}"

    def pdf_worker():
        """Lesen im eigenen Prozess – im gebündelten Programm startet dafür dieselbe EXE als Kindprozess."""
        import pymupdf

        from zotivity.extract.worker import ExtractionWorker

        path = home / "selftest.pdf"
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), "Lese-Prozess: Selbsttest")
        doc.save(path)
        worker = ExtractionWorker()
        try:
            result = worker.call(path, "application/pdf", timeout=120)
        finally:
            worker.stop()
        assert "Selbsttest" in result.pages[0].text, result
        return "ok"

    def vectors():
        import numpy as np

        from zotivity.index.vectors import VectorIndex  # noqa: F401

        a = np.random.default_rng(1).standard_normal((50, 64)).astype(np.float16)
        return f"NumPy {np.__version__}, {a.shape}"

    def keystore():
        from zotivity.keystore import get_store

        info = get_store().backend_info()
        assert info["secure"], info
        return info["backend"]

    def server():
        import httpx
        import uvicorn

        from zotivity.engine import Engine
        from zotivity.server.app import create_app

        app = create_app(Engine())
        cfg = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", log_config=None, access_log=False)
        srv = uvicorn.Server(cfg)
        import threading

        th = threading.Thread(target=srv.run, daemon=True)
        th.start()
        for _ in range(200):
            if srv.started:
                break
            time.sleep(0.05)
        assert srv.started, "Server startet nicht"
        port = srv.servers[0].sockets[0].getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        checked = []
        try:
            with httpx.Client(base_url=base, timeout=20, trust_env=False) as c:
                page = c.get("/")
                assert page.status_code == 200 and "Zotivity" in page.text
                from zotivity import __version__

                assert f"/static/v{__version__}/js/main.js" in page.text, "Modulpfad je Version fehlt"
                for path in ("/static/js/main.js", f"/static/v{__version__}/js/main.js", "/static/css/app.css",
                             "/static/js/views/settings.js", "/static/js/views/search.js", "/static/js/views/help.js",
                             "/static/js/i18n/en.js", "/static/help/de.md", "/static/help/en.md",
                             "/static/js/views/embedmodels.js", "/api/embedding/local",
                             "/static/img/icon.svg", "/api/catalog", "/api/settings/defaults", "/api/status",
                             "/api/setup", "/api/corpora", "/api/library/status", "/plugin/zotivity.xpi",
                             # Modul „Recherche“ (zotivity.research): Ansicht und Schnittstelle
                             "/static/js/views/research.js", "/static/js/views/research/screening.js",
                             "/static/css/research.css", "/api/research/info", "/api/research/projects"):
                    r = c.get(path)
                    assert r.status_code == 200, f"{path}: {r.status_code}"
                    checked.append(path)
                r = c.put("/api/settings", json={"retrieval": {"top_k": 9}}, headers={"X-Zotivity": "1"})
                assert r.status_code == 200 and r.json()["retrieval"]["top_k"] == 9
        finally:
            srv.should_exit = True
            th.join(10)
        return f"{len(checked)} Adressen"

    def webview_backend():
        import webview  # noqa: F401

        if sys.platform == "win32":
            import clr  # noqa: F401  (pythonnet / .NET)
            from webview.platforms import winforms  # noqa: F401  (lädt die WebView2-Bibliotheken)

            lib = Path(webview.__file__).parent / "lib"
            assert any(lib.rglob("Microsoft.Web.WebView2.Core.dll")), "WebView2-Bibliotheken fehlen"
        return "ok"

    def window():
        """Echtes Fenster mit denselben Startoptionen wie das Programm öffnen, JavaScript ausführen, schliessen."""
        import webview

        from zotivity.desktop import set_webview_zoom, start_options

        result: dict = {}
        w = webview.create_window("Zotivity Selbsttest", html="<!doctype html><p>ok</p>", width=320, height=200,
                                  x=-4000, y=-4000, focus=False)

        def check():
            try:
                result["loaded"] = w.events.loaded.wait(30)
                result["js"] = w.evaluate_js("1 + 1")
                before = w.evaluate_js("window.devicePixelRatio")
                result["zoom_set"] = set_webview_zoom(w, 1.5)
                time.sleep(0.5)
                result["zoom"] = w.evaluate_js("window.devicePixelRatio") / before
            finally:
                w.destroy()

        webview.start(check, private_mode=True, **start_options())
        assert result.get("loaded"), "Fenster lädt nicht"
        assert result.get("js") == 2, f"JavaScript: {result.get('js')!r}"
        assert result.get("zoom_set") and abs(result.get("zoom", 0) - 1.5) < 0.2, f"Zoom der Oberfläche: {result.get('zoom')!r}"
        return "geöffnet, JavaScript und Zoom ok"

    def languages_and_export():
        """Wörterbuch des Dienstes (wird dynamisch geladen – fehlt es im Paket, bleibt alles deutsch) und Word-Export."""
        from xml.dom import minidom

        from zotivity import exporting, i18n

        assert i18n.tr("Fertig", "en") == "Done", "englisches Wörterbuch fehlt"
        assert i18n.tr("Indexierung: X", "en") == "Indexing: X"
        assert [b.kind for b in exporting.blocks("## A\n\nText **fett**\n\n- Punkt")] == ["heading", "para", "item"]
        minidom.parseString(exporting._STYLES_XML)  # Word-Vorlage gültig
        return "Deutsch, Englisch; Export bereit"

    def embedding_runtime():
        """llama-server startet (alle DLLs vorhanden), Modellkatalog und Testsatz sind lesbar."""
        from zotivity.embeddings import benchmark, model_catalog
        from zotivity.embeddings.llama_runtime import find_server, server_version

        exe = find_server()
        assert exe is not None, "llama-server fehlt im Paket"
        version = server_version(str(exe))
        assert version, "llama-server startet nicht (fehlende DLL?)"
        cat = model_catalog.bundled()
        assert len(cat.models) >= 5 and any(m.default for m in cat.models), "Modellkatalog unvollständig"
        assert benchmark.bench_set()["queries"], "Testsatz fehlt"
        return f"llama.cpp {version}, Katalog {cat.version} mit {len(cat.models)} Modellen"

    def llm_sdks():
        import anthropic
        import google.genai
        import openai

        return f"anthropic {anthropic.__version__}, openai {openai.__version__}, google-genai {google.genai.__version__}"

    step("PDF lesen", pdf)
    step("PDF lesen im eigenen Prozess", pdf_worker)
    step("Vektoren", vectors)
    step("Schlüsselspeicher", keystore)
    step("Dienst und Oberfläche", server)
    step("Programmfenster (WebView2)", webview_backend)
    step("Sprachmodell-Bibliotheken", llm_sdks)
    step("Eingebaute Embedding-Laufzeit", embedding_runtime)
    step("Sprachen und Export", languages_and_export)
    if "--no-window" not in sys.argv:
        step("Fenster öffnen", window)
    (out / "selftest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if report["errors"] else 0
