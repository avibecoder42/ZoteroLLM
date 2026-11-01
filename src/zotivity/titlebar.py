"""Windows: Titelleiste des Programmfensters im Farbschema der Oberfläche (hell, grau, dunkel).

Windows 10 (ab 20H1) kennt nur hell oder dunkel (DWMWA_USE_IMMERSIVE_DARK_MODE), Windows 11 zusätzlich eigene
Farben für Leiste, Rahmen und Schrift. Ältere Systeme übergehen die Angaben; auf anderen Systemen tut das Modul
nichts. Die Oberfläche meldet ihre Farben nach jedem Wechsel des Farbschemas (main.js → JsApi.set_title_bar).
"""

from __future__ import annotations

import re
import sys

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

# Farben der Oberfläche (app.css: --surface, --ink, --line) für den Start, bevor die Seite geladen ist
THEMES = {
    "light": (False, "#ffffff", "#1c1b1a", "#e4e2dc"),
    "dark": (True, "#1b1b1c", "#efeef0", "#2f2f32"),
    "gray": (True, "#333438", "#f1f0f2", "#46474c"),
}


def colorref(value) -> int | None:
    """„#1b1b1c“, „#fff“ oder „rgb(27, 27, 28)“ → COLORREF (0x00BBGGRR); Unbekanntes → None."""
    s = str(value or "").strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", s)
    if m:
        hx = m.group(1)
        if len(hx) == 3:
            hx = "".join(c * 2 for c in hx)
        r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
    else:
        m = re.fullmatch(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*[\d.]+\s*)?\)", s)
        if not m:
            return None
        r, g, b = (min(255, int(x)) for x in m.groups())
    return r | (g << 8) | (b << 16)


def apply(hwnd: int, dark: bool, caption=None, text=None, border=None) -> bool:
    """Titelleiste eines Fensters einfärben. True, wenn Windows den hellen/dunklen Modus übernommen hat."""
    if sys.platform != "win32" or not hwnd:
        return False
    import ctypes
    from ctypes import wintypes

    try:
        dwm = ctypes.WinDLL("dwmapi")
        user32 = ctypes.WinDLL("user32")
    except OSError:
        return False
    handle = wintypes.HWND(hwnd)

    def put(attr: int, value: int, kind) -> bool:
        v = kind(value)
        return dwm.DwmSetWindowAttribute(handle, wintypes.DWORD(attr), ctypes.byref(v), ctypes.sizeof(v)) == 0

    ok = put(DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0, ctypes.c_int)
    for attr, value in ((DWMWA_CAPTION_COLOR, caption), (DWMWA_BORDER_COLOR, border), (DWMWA_TEXT_COLOR, text)):
        c = colorref(value)
        if c is not None:
            put(attr, c, wintypes.DWORD)  # Windows 10: nicht unterstützt, wird übergangen
    # Rahmen neu zeichnen – Windows 10 übernähme den dunklen Modus sonst erst beim nächsten Aktivieren
    swp = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020  # NOSIZE, NOMOVE, NOZORDER, NOACTIVATE, FRAMECHANGED
    user32.SetWindowPos(handle, None, 0, 0, 0, 0, swp)
    return ok


def apply_theme(hwnd: int, mode: str) -> bool:
    """Start: Farben des gespeicherten Farbschemas (light, dark, gray)."""
    dark, caption, text, border = THEMES.get(mode, THEMES["light"])
    return apply(hwnd, dark, caption, text, border)
