"""Programmfenster mit eingebettetem Dienst (Windows; unter macOS/Linux ebenfalls lauffähig).

Aufruf::

    Zotivity.exe                      Fenster öffnen
    Zotivity.exe --background         Dienst ohne Fenster (vom Zotero-Plugin gestartet); Fenster bei Bedarf
    Zotivity.exe serve|index|mcp|…    Befehle der Kommandozeile (siehe ``zotivity --help``)

Läuft Zotivity bereits (z. B. vom Plugin im Hintergrund gestartet), bittet ein zweiter Start den
laufenden Prozess, sein Fenster zu zeigen, und beendet sich sofort wieder.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from zotivity import __version__, paths

log = logging.getLogger(__name__)

APP_NAME = "Zotivity"
MUTEX_NAME = "ZotivityRunningMutex"  # vom Installer erkannt (AppMutex)
CLI_COMMANDS = {"serve", "index", "search", "ask", "keys", "status", "plugin", "mcp", "--version", "-h", "--help"}
OPEN_SCHEMES = ("zotero:", "http:", "https:", "mailto:")


# ---------------------------------------------------------------------------------- Hilfen
def _create_mutex() -> None:
    if sys.platform == "win32":
        import ctypes

        # Handle bewusst nicht schliessen: Der Mutex lebt so lange wie der Prozess
        _create_mutex.handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)


def _message_box(text: str, title: str = APP_NAME, flags: int = 0x40) -> int:
    """Systemdialog (Windows). Rückgabe: 6 = Ja, 7 = Nein, 2 = Abbrechen, 1 = OK."""
    if sys.platform == "win32":
        import ctypes

        return ctypes.windll.user32.MessageBoxW(None, text, title, flags | 0x10000)  # MB_SETFOREGROUND
    print(text, file=sys.stderr)
    return 1


def _windows_dark_mode() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def _background_color(appearance: str) -> str:
    dark = appearance == "dark" or appearance == "gray" or (appearance == "system" and _windows_dark_mode())
    return {"gray": "#2a2b2e"}.get(appearance, "#121212" if dark else "#f4f3f0")


def _theme_mode(appearance: str) -> str:
    """Farbschema der Oberfläche: „system“ folgt Windows."""
    if appearance in ("light", "dark", "gray"):
        return appearance
    return "dark" if _windows_dark_mode() else "light"


def open_external(url: str) -> bool:
    """zotero://, https:// usw. mit dem zuständigen Programm öffnen (nie im Programmfenster)."""
    if not isinstance(url, str) or not url.lower().startswith(OPEN_SCHEMES):
        return False
    if sys.platform == "win32":
        os.startfile(url)  # noqa: S606 - nur geprüfte Schemata
    elif sys.platform == "darwin":
        subprocess.Popen(["open", url])  # noqa: S603, S607
    else:
        try:
            subprocess.Popen(["xdg-open", url])  # noqa: S603, S607
        except OSError:
            webbrowser.open(url)
    return True


def _running_instance() -> dict | None:
    """Läuft bereits ein Zotivity-Dienst? Dann dessen Statusdaten."""
    import httpx

    from zotivity.service import read_state

    state = read_state()
    if not state:
        return None
    try:
        r = httpx.get(state["url"] + "api/app/info", timeout=2.5, trust_env=False)
        return state if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


# ---------------------------------------------------------------------------------- Fenstergrösse
MIN_SIZE = (900, 600)


def _window_file() -> Path:
    return paths.config_dir() / "window.json"


def _screens() -> list[tuple[int, int, int, int]]:
    """Bildschirme (x, y, Breite, Höhe) in logischen Pixeln."""
    try:
        import webview

        return [(s.x, s.y, s.width, s.height) for s in webview.screens]
    except Exception:  # noqa: BLE001 - ohne Angaben: Standardgrösse
        return []


def default_geometry(screens: list[tuple[int, int, int, int]]) -> dict:
    """Erste Fenstergrösse: passend zum Hauptbildschirm, aber höchstens 16:9 breit."""
    if not screens:
        return {"width": 1320, "height": 860, "x": None, "y": None, "maximized": False}
    x, y, w, hgt = screens[0]
    height = max(MIN_SIZE[1], int(hgt * 0.86))
    width = max(MIN_SIZE[0], min(int(w * 0.9), int(height * 16 / 9)))
    return {"width": width, "height": height, "x": x + (w - width) // 2, "y": y + max(0, (hgt - height) // 3),
            "maximized": False}


def load_geometry(screens: list[tuple[int, int, int, int]] | None = None) -> dict:
    """Fenstergrösse und -position vom letzten Start – nur wenn das Fenster noch auf einem Bildschirm läge."""
    import json

    screens = _screens() if screens is None else screens
    fallback = default_geometry(screens)
    try:
        g = json.loads(_window_file().read_text(encoding="utf-8"))
        width, height = int(g["width"]), int(g["height"])
        x, y = int(g["x"]), int(g["y"])
    except (OSError, ValueError, KeyError, TypeError):
        return fallback
    width, height = max(MIN_SIZE[0], width), max(MIN_SIZE[1], height)
    if screens:
        # Titelleiste (oberer Rand, ein Stück vom linken Rand) muss auf einem Bildschirm liegen
        visible = any(sx <= x + 60 <= sx + sw and sy <= y + 10 <= sy + sh for sx, sy, sw, sh in screens)
        if not visible:
            return {**fallback, "maximized": bool(g.get("maximized"))}
        sx, sy, sw, sh = next(s for s in screens if s[0] <= x + 60 <= s[0] + s[2] and s[1] <= y + 10 <= s[1] + s[3])
        width, height = min(width, sw), min(height, sh)
    return {"width": width, "height": height, "x": x, "y": y, "maximized": bool(g.get("maximized"))}


class WindowGeometry:
    """Verfolgt Grösse und Position (des nicht maximierten Fensters) und speichert sie beim Schliessen."""

    def __init__(self, start: dict):
        self.width, self.height = start["width"], start["height"]
        self.x, self.y = start.get("x"), start.get("y")
        self.maximized = bool(start.get("maximized"))
        self.minimized = False

    def attach(self, window) -> None:
        ev = window.events
        ev.resized += self.on_resized
        ev.moved += self.on_moved
        ev.maximized += self.on_maximized
        ev.minimized += self.on_minimized
        ev.restored += self.on_restored

    def on_resized(self, width, height):
        if not self.maximized and not self.minimized and width >= MIN_SIZE[0] // 2:
            self.width, self.height = int(width), int(height)

    def on_moved(self, x, y):
        if not self.maximized and not self.minimized and x > -20000 and y > -20000:  # minimiert: -32000
            self.x, self.y = int(x), int(y)

    def on_maximized(self):
        self.maximized, self.minimized = True, False

    def on_minimized(self):
        self.minimized = True

    def on_restored(self):
        if self.minimized:
            self.minimized = False  # zurück in den vorherigen Zustand (maximiert bleibt maximiert)
        else:
            self.maximized = False

    def save(self) -> None:
        import json

        if self.x is None or self.y is None:
            return
        data = {"width": self.width, "height": self.height, "x": self.x, "y": self.y, "maximized": self.maximized}
        try:
            path = _window_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            log.debug("Fenstergrösse nicht gespeichert", exc_info=True)


# ---------------------------------------------------------------------------------- Fensterseite
def set_webview_zoom(window, factor: float) -> bool:
    """Zoom der Oberfläche im Programmfenster – wie Strg + Mausrad: mit neuem Umbruch, nicht nur vergrössert."""
    native = getattr(window, "native", None)
    view = getattr(native, "webview", None)
    if view is None:
        return False
    from System import Action  # WinForms-Thread; pythonnet ist mit pywebview geladen

    native.Invoke(Action(lambda: setattr(view, "ZoomFactor", float(factor))))
    return True


class JsApi:
    """Funktionen für die Oberfläche (window.pywebview.api.*). Laufen in eigenen Threads."""

    def __init__(self, host: DesktopHost):
        self._host = host

    def set_zoom(self, factor):
        return set_webview_zoom(self._host.window, max(0.5, min(2.5, float(factor))))

    def open_url(self, url):
        return open_external(url)

    def save_text(self, filename, text):
        path = self._ask_save_path(filename)
        if not path:
            return False
        Path(path).write_text(text, encoding="utf-8")
        return path

    def save_url(self, filename, url):
        import httpx

        if not isinstance(url, str) or not url.startswith("/"):
            return False
        path = self._ask_save_path(filename)
        if not path:
            return False
        r = httpx.get(self._host.base_url.rstrip("/") + url, timeout=60, trust_env=False)
        r.raise_for_status()
        Path(path).write_bytes(r.content)
        return path

    def set_title_bar(self, dark, caption=None, text=None, border=None):
        """Titelleiste im Farbschema der Oberfläche (main.js ruft das nach jedem Wechsel des Farbschemas auf)."""
        from zotivity import titlebar

        return any([titlebar.apply(hwnd, bool(dark), caption, text, border) for hwnd in self._host.hwnds()])

    def reveal(self, path):
        p = Path(str(path))
        if not p.is_dir():
            return False
        return open_external(p.as_uri()) if sys.platform != "win32" else (os.startfile(str(p)) or True)  # noqa: S606

    def _ask_save_path(self, filename: str) -> str | None:
        import webview

        downloads = Path.home() / "Downloads"
        kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
        result = self._host.window.create_file_dialog(kind, directory=str(downloads if downloads.is_dir() else Path.home()),
                                                      save_filename=Path(str(filename)).name)
        if not result:
            return None
        return result if isinstance(result, str) else result[0]


class DesktopHost:
    def __init__(self, background: bool, exit_with_zotero: int | None):
        self.background = background
        self.exit_with_zotero = exit_with_zotero
        self.window = None
        self.server = None
        self.engine = None
        self.base_url = ""
        self.visible = not background
        self.quitting = False
        self.quit_when_idle = False
        self._pending_open: dict | None = None
        self.geometry: WindowGeometry | None = None

    # -- Dienst --------------------------------------------------------------------------
    def start_server(self) -> None:
        import uvicorn

        from zotivity.engine import Engine
        from zotivity.server.app import create_app
        from zotivity.service import write_state

        self.engine = Engine()
        cfg = self.engine.settings.server
        app = create_app(self.engine, on_exit=self.quit, exit_after_minutes=self.exit_with_zotero,
                         on_open_ui=self.show, on_idle_exit=self.quit_if_hidden)
        config = uvicorn.Config(app, host=cfg.host, port=cfg.port, log_level="warning", access_log=False,
                                log_config=None, timeout_graceful_shutdown=5)
        self.server = uvicorn.Server(config)
        self.base_url = f"http://{cfg.host}:{cfg.port}/"
        thread = threading.Thread(target=self.server.run, name="uvicorn", daemon=True)
        thread.start()
        for _ in range(200):
            if self.server.started:
                break
            if not thread.is_alive():
                raise RuntimeError(f"Der Dienst konnte nicht starten – ist Port {cfg.port} belegt?")
            time.sleep(0.05)
        write_state(cfg.host, cfg.port)
        log.info("Zotivity %s (Programmfenster) auf %s", __version__, self.base_url)

    def running_jobs(self) -> list:
        if not self.engine:
            return []
        return [j for j in self.engine.jobs.list() if j["status"] in ("queued", "running")]

    # -- Fenster -------------------------------------------------------------------------
    def show(self, params: dict | None = None) -> bool:
        """Fenster zeigen (auch aus dem Hintergrund) und optional eine Ansicht öffnen."""
        if not self.window:
            self._pending_open = params
            return False
        self.window.show()
        self.visible = True
        self.quit_when_idle = False
        self._focus()  # stellt auch ein minimiertes Fenster wieder her (ohne ein maximiertes zu verkleinern)
        if params:
            import json

            self.window.evaluate_js(f"window.zllmOpen && window.zllmOpen({json.dumps(params)})")
        return True

    def hwnds(self) -> list[int]:
        """Fenster-Handle des Programmfensters (Windows; pywebview mit WinForms, sonst alle eigenen Fenster)."""
        native = getattr(self.window, "native", None)
        try:
            if native is not None:
                return [int(native.Handle.ToInt64())]
        except Exception:  # noqa: BLE001 - andere Fensterbibliothek
            pass
        from zotivity.winfocus import own_windows

        return own_windows()

    def color_title_bar(self, mode: str) -> None:
        """Beim Start: Titelleiste schon im gespeicherten Farbschema, bevor die Oberfläche geladen ist."""
        from zotivity import titlebar

        try:
            for hwnd in self.hwnds():
                titlebar.apply_theme(hwnd, mode)
        except Exception:  # noqa: BLE001 - nur Darstellung
            log.debug("Titelleiste nicht eingefärbt", exc_info=True)

    def _focus(self) -> None:
        from zotivity.winfocus import bring_to_front, own_windows

        try:
            time.sleep(0.15)  # bis das Fenster sichtbar ist
            for hwnd in own_windows():
                bring_to_front(hwnd)
        except Exception:  # noqa: BLE001 - Komfort
            pass

    def hide(self) -> None:
        if self.window:
            self.window.hide()
        self.visible = False

    def on_closing(self):
        """Schliessen-Knopf: Zotivity beenden – auch wenn es vom Zotero-Plugin gestartet wurde (das Plugin startet
        den Dienst bei Bedarf wieder). Nur laufende Aufträge dürfen auf Wunsch im Hintergrund zu Ende laufen.
        Früher blieb ein vom Plugin gestarteter Dienst nach dem Schliessen unsichtbar aktiv – für Nutzerinnen und
        Nutzer nicht erkennbar, und das Setup meldete dann eine laufende Instanz."""
        if self.quitting:
            return True
        jobs = [j for j in self.running_jobs() if j["kind"] in ("index", "review", "sheets", "pull", "catalog")]
        if jobs:
            from zotivity.i18n import tr

            titles = "\n".join(f"• {j['title']}" for j in jobs)  # as_dict liefert die Titel schon übersetzt
            waiting = self.engine.index_queue.entries() if self.engine else []
            if waiting:
                titles += "\n" + "\n".join(f"• {tr(e['title'])} ({tr('wartet')})" for e in waiting)
            answer = _message_box(
                tr("Es läuft noch:") + f"\n{titles}\n\n" + tr(
                    "Ja – im Hintergrund weiterlaufen lassen; Zotivity beendet sich danach von selbst.") + "\n"
                + tr("Nein – abbrechen und Zotivity beenden.") + "\n" + tr("Abbrechen – Fenster offen lassen."),
                flags=0x3 | 0x20)  # MB_YESNOCANCEL | MB_ICONQUESTION
            if answer == 6:
                self.quit_when_idle = True  # beendet sich nach den Aufträgen (siehe _watch)
                self.hide()
                return False
            if answer == 2:
                return False
            self.engine.index_queue.clear()  # sonst startete nach dem Abbruch gleich der nächste Lauf
            for j in jobs:
                self.engine.jobs.cancel(j["id"])
        self.quitting = True
        self._stop_server()
        return True

    def quit(self) -> None:
        """Programm beenden (Menü, Update, Zotero geschlossen)."""
        self.quitting = True
        self._stop_server()
        if self.window:
            try:
                self.window.destroy()
            except Exception:  # noqa: BLE001
                os._exit(0)

    def quit_if_hidden(self) -> bool:
        """Zotero ist geschlossen: nur beenden, wenn niemand das Fenster benutzt."""
        if self.visible:
            return False
        self.quit()
        return True

    def _stop_server(self) -> None:
        from zotivity.service import clear_state

        if self.geometry:
            self.geometry.save()
        if self.server:
            self.server.should_exit = True
        clear_state()

    def _watch(self) -> None:
        """Nach „im Hintergrund weiterlaufen“: beenden, sobald nichts mehr läuft."""
        while not self.quitting:
            time.sleep(5)
            if self.quit_when_idle and not self.visible and not self.running_jobs():
                log.info("Hintergrundaufträge beendet – Zotivity wird geschlossen.")
                self.quit()
                return

    def on_loaded(self) -> None:
        if self._pending_open is not None and self.base_url:
            params, self._pending_open = self._pending_open, None
            self.show(params)


# ---------------------------------------------------------------------------------- Start
def run_desktop(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--background", action="store_true", help="ohne Fenster starten (Zotero-Plugin)")
    parser.add_argument("--exit-with-zotero", type=int, metavar="MIN")
    parser.add_argument("--open", default="", help="Ansicht öffnen, z. B. view=ask&collection=users/0:KEY")
    parser.add_argument("--debug", action="store_true")
    args, _unknown = parser.parse_known_args(argv)

    from urllib.parse import parse_qsl

    from zotivity.cli import setup_logging

    setup_logging(quiet=True)
    params = dict(parse_qsl(args.open)) if args.open else None

    # Bereits gestartet? Dann dort das Fenster zeigen.
    existing = _running_instance()
    if existing:
        if args.background:
            return 0
        import httpx

        from zotivity.winfocus import allow_foreground_for_others

        allow_foreground_for_others()
        try:
            r = httpx.post(existing["url"] + "api/ui/open", json=params or {}, headers={"X-Zotivity": "1"},
                           timeout=5, trust_env=False)
            if r.status_code == 200 and r.json().get("shown"):
                return 0
        except httpx.HTTPError:
            pass
        # Laufender Dienst ohne Fenster (z. B. „zotivity serve“): im Browser öffnen
        webbrowser.open(existing["url"])
        return 0

    _create_mutex()
    import webview

    host = DesktopHost(background=args.background, exit_with_zotero=args.exit_with_zotero)
    appearance = _appearance()
    geo = load_geometry()
    # Das Fenster erscheint sofort mit einer Startanzeige; der Dienst lädt währenddessen im Hintergrund.
    window = webview.create_window(
        APP_NAME, html=_splash_html(appearance), js_api=JsApi(host), width=geo["width"], height=geo["height"],
        x=geo["x"], y=geo["y"], maximized=geo["maximized"], min_size=MIN_SIZE,
        hidden=args.background, background_color=_background_color(appearance), text_select=True, zoomable=True,
    )
    host.window = window
    host.geometry = WindowGeometry(geo)
    host.geometry.attach(window)
    window.events.closing += host.on_closing
    window.events.loaded += host.on_loaded
    window.events.shown += lambda: host.color_title_bar(_theme_mode(appearance))

    def boot():
        try:
            host.start_server()
        except Exception as e:  # noqa: BLE001
            log.exception("Start fehlgeschlagen")
            from zotivity.i18n import tr

            _message_box(tr("Zotivity konnte nicht starten:") + f"\n\n{tr(str(e))}", flags=0x10)
            host.quit()
            return
        window.load_url(host.base_url + (("?" + args.open) if args.open else ""))
        host._watch()

    storage = paths.data_dir() / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(boot, private_mode=False, storage_path=str(storage), debug=args.debug, **start_options())
    host.quitting = True
    host._stop_server()
    return 0


def start_options() -> dict:
    """Gemeinsame Optionen für webview.start (Programm und Selbsttest).

    Fenstersymbol: unter Windows aus der EXE – pywebview lädt eine übergebene Datei als .NET-Icon, das kein PNG
    versteht und dann abstürzt; unter Linux (GTK/Qt) aus dem PNG."""
    icon = Path(__file__).parent / "server" / "static" / "img" / "icon.png"
    use_icon = sys.platform not in ("win32", "darwin") and icon.exists()
    return {"icon": str(icon) if use_icon else None}


def _appearance() -> str:
    """Farbschema aus den Einstellungen lesen, ohne den ganzen Dienst zu laden."""
    import json

    try:
        return json.loads(paths.settings_file().read_text(encoding="utf-8")).get("appearance", "system")
    except (OSError, ValueError):
        return "system"


def _splash_html(appearance: str) -> str:
    bg = _background_color(appearance)
    dark = bg != "#f4f3f0"
    ink, sub, line, accent = (("#efeef0", "#85848b", "#2f2f32", "#aaa5ff") if dark
                              else ("#1c1b1a", "#86847d", "#e4e2dc", "#4a43c4"))
    svg = (Path(__file__).parent / "server" / "static" / "img" / "icon.svg").read_text(encoding="utf-8")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{height:100%;margin:0;background:{bg};color:{ink};font:14px "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;overflow:hidden}}
.s{{height:100%;display:grid;place-content:center;justify-items:center;gap:12px}}
.s svg{{width:56px;height:56px;animation:b 2.2s ease-in-out infinite}}@keyframes b{{50%{{transform:scale(.94);opacity:.85}}}}
h1{{margin:0;font-size:26px;font-weight:650;letter-spacing:-.02em}}p{{margin:0;color:{sub}}}
.p{{position:relative;width:180px;height:3px;border-radius:2px;overflow:hidden;background:{line}}}
.p i{{position:absolute;top:0;bottom:0;width:40%;border-radius:2px;background:{accent};animation:r 1.6s ease-in-out infinite}}
@keyframes r{{0%{{left:-40%}}100%{{left:100%}}}}</style></head>
<body><div class="s">{svg}<h1>Zotivity</h1><div class="p"><i></i></div><p>wird gestartet …</p></div></body></html>"""


def entry() -> int:
    """Startpunkt des Programms (gebündelte EXE und ``zotivity-app``)."""
    import multiprocessing

    # Gebündeltes Programm: Kindprozesse (Lese-Prozess der Indexierung) starten über dieselbe EXE
    multiprocessing.freeze_support()
    argv = sys.argv[1:]
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if argv and argv[0] in CLI_COMMANDS:
        from zotivity.cli import main

        main(argv)
        return 0
    if argv and argv[0] == "--self-test":
        from zotivity.selftest import run

        return run(argv[1] if len(argv) > 1 else ".")
    return run_desktop(argv)


if __name__ == "__main__":
    sys.exit(entry())
