"""Programmfenster und Updates: die Teile, die ohne echtes Fenster prüfbar sind."""

import sys

from fastapi.testclient import TestClient

from zotivity import desktop, updates
from zotivity.server.app import create_app

H = {"X-Zotivity": "1"}


def test_open_external_only_known_schemes(monkeypatch):
    opened = []
    monkeypatch.setattr(desktop.os, "startfile", lambda u: opened.append(u), raising=False)
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda args: opened.append(args[-1]))
    assert desktop.open_external("zotero://select/library/items/ABCD1234")
    assert desktop.open_external("https://example.org")
    for bad in ("file:///C:/Windows/system32/calc.exe", "javascript:alert(1)", "C:\\x.exe", None):
        assert not desktop.open_external(bad)
    assert len(opened) == 2


def test_window_icon_never_passed_as_png_on_windows():
    """pywebview lädt eine übergebene Icon-Datei unter Windows als .NET-Icon – ein PNG lässt das Programm abstürzen."""
    icon = desktop.start_options()["icon"]
    if sys.platform in ("win32", "darwin"):
        assert icon is None
    else:
        assert icon is None or icon.endswith(".png")


def test_splash_follows_theme():
    light = desktop._splash_html("light")
    dark = desktop._splash_html("dark")
    assert "Zotivity" in light and "<svg" in light
    assert "#f4f3f0" in light and "#121212" in dark


def test_cli_commands_bypass_window(monkeypatch):
    called = {}
    monkeypatch.setattr(sys, "argv", ["Zotivity.exe", "status"])
    monkeypatch.setattr("zotivity.cli.main", lambda argv: called.setdefault("cli", argv))
    monkeypatch.setattr(desktop, "run_desktop", lambda argv: called.setdefault("desktop", argv) and 0)
    assert desktop.entry() == 0
    assert called == {"cli": ["status"]}


def test_ui_open_endpoint(zengine):
    shown = []
    with TestClient(create_app(zengine, on_open_ui=lambda p: shown.append(p) or True)) as c:
        r = c.post("/api/ui/open", json={"view": "ask", "collection": "users/0:ABCD1234", "evil": "x"}, headers=H)
        assert r.json() == {"shown": True}
        assert shown == [{"view": "ask", "collection": "users/0:ABCD1234"}]
        assert c.get("/api/app/info").json()["desktop"] is True
    with TestClient(create_app(zengine)) as c:
        assert c.post("/api/ui/open", json={}, headers=H).json() == {"shown": False}


SCREEN = [(0, 0, 3413, 1440)]  # Breitbild (logische Pixel)


def test_first_window_fits_screen_but_not_wider_than_16_9():
    g = desktop.default_geometry(SCREEN)
    assert g["height"] <= 1440 and g["width"] <= g["height"] * 16 / 9 + 1
    assert 0 <= g["x"] and g["x"] + g["width"] <= 3413
    assert desktop.default_geometry([(0, 0, 1280, 720)])["width"] >= desktop.MIN_SIZE[0]
    assert desktop.default_geometry([])["x"] is None


def test_window_geometry_is_remembered(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "_window_file", lambda: tmp_path / "window.json")
    assert desktop.load_geometry(SCREEN) == desktop.default_geometry(SCREEN)  # erster Start
    geo = desktop.WindowGeometry(desktop.load_geometry(SCREEN))
    geo.on_resized(1500, 900)
    geo.on_moved(200, 100)
    geo.on_maximized()
    geo.on_resized(3413, 1400)  # maximiert: zählt nicht als normale Grösse
    geo.on_moved(-8, -8)
    geo.save()
    g = desktop.load_geometry(SCREEN)
    assert (g["width"], g["height"], g["x"], g["y"], g["maximized"]) == (1500, 900, 200, 100, True)
    # Wiederhergestellt und minimiert: die Lage des normalen Fensters bleibt
    geo.on_restored()
    geo.on_minimized()
    geo.on_moved(-32000, -32000)
    geo.on_restored()
    geo.save()
    assert desktop.load_geometry(SCREEN)["maximized"] is False and desktop.load_geometry(SCREEN)["x"] == 200


def test_window_off_screen_is_placed_anew(tmp_path, monkeypatch):
    path = tmp_path / "window.json"
    monkeypatch.setattr(desktop, "_window_file", lambda: path)
    path.write_text('{"width": 1200, "height": 800, "x": 5000, "y": 100, "maximized": false}', encoding="utf-8")
    g = desktop.load_geometry(SCREEN)
    assert g["x"] == desktop.default_geometry(SCREEN)["x"]
    path.write_text('{"width": 9000, "height": 9000, "x": 10, "y": 10}', encoding="utf-8")
    g = desktop.load_geometry(SCREEN)
    assert (g["width"], g["height"]) == (3413, 1440)  # nicht grösser als der Bildschirm
    path.write_text("kaputt", encoding="utf-8")
    assert desktop.load_geometry(SCREEN) == desktop.default_geometry(SCREEN)


def test_version_order():
    assert updates.version_tuple("0.10.0") > updates.version_tuple("0.9.3")
    assert updates.version_tuple("1.0") == updates.version_tuple("1.0.0.0")
    assert updates.version_tuple("0.2.0b1") > updates.version_tuple("0.1.9")


def test_zoom_without_native_window_does_nothing():
    from types import SimpleNamespace

    from zotivity.desktop import JsApi, set_webview_zoom

    assert set_webview_zoom(SimpleNamespace(native=None), 1.25) is False
    assert JsApi(SimpleNamespace(window=SimpleNamespace())).set_zoom(9) is False
