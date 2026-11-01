"""Windows: Zotero-Dialoge (z. B. die Freigabe des Schreibzugriffs) in den Vordergrund holen.

Zotero öffnet den Bestätigungsdialog oft hinter anderen Fenstern. Während die Anfrage läuft,
werden neu erscheinende Fenster von zotero.exe nach vorne geholt. Auf anderen Systemen tut
das Modul nichts.
"""

from __future__ import annotations

import sys
import threading

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.argtypes = [_EnumProc, wintypes.LPARAM]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, wintypes.UINT]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                     ctypes.POINTER(wintypes.DWORD)]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _HWND_TOPMOST, _HWND_NOTOPMOST = wintypes.HWND(-1), wintypes.HWND(-2)
    _SWP_NOMOVE, _SWP_NOSIZE, _SWP_SHOWWINDOW = 0x2, 0x1, 0x40
    _SW_RESTORE = 9

    def _process_name(pid: int) -> str:
        h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value.rsplit("\\", 1)[-1].lower()
            return ""
        finally:
            _kernel32.CloseHandle(h)

    def _visible_windows(match) -> list[int]:
        found: list[int] = []

        def cb(hwnd, _):
            if _user32.IsWindowVisible(hwnd):
                pid = wintypes.DWORD()
                _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if match(pid.value):
                    found.append(int(hwnd))
            return True

        _user32.EnumWindows(_EnumProc(cb), 0)
        return found

    def zotero_windows() -> list[int]:
        """Sichtbare Hauptfenster von zotero.exe (in Z-Reihenfolge, oberstes zuerst)."""
        names: dict[int, str] = {}

        def is_zotero(pid: int) -> bool:
            if pid not in names:
                names[pid] = _process_name(pid)
            return names[pid] == "zotero.exe"

        return _visible_windows(is_zotero)

    def own_windows() -> list[int]:
        """Sichtbare Fenster dieses Prozesses (das Programmfenster)."""
        me = _kernel32.GetCurrentProcessId()
        return _visible_windows(lambda pid: pid == me)

    def allow_foreground_for_others() -> None:
        """Erlaubt einem anderen Prozess (dem laufenden Zotivity), sein Fenster nach vorne zu holen."""
        _user32.AllowSetForegroundWindow(wintypes.DWORD(-1 & 0xFFFFFFFF))

    def bring_to_front(hwnd: int) -> None:
        if _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, _SW_RESTORE)
        # Kurz „immer oben“ setzen und wieder lösen: hebt das Fenster auch dann nach vorn,
        # wenn Windows den Fokuswechsel aus einem anderen Prozess verweigert.
        flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW
        _user32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0, flags)
        _user32.SetWindowPos(hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        _user32.SetForegroundWindow(hwnd)

else:  # pragma: no cover - nur Windows

    def zotero_windows() -> list[int]:
        return []

    def own_windows() -> list[int]:
        return []

    def allow_foreground_for_others() -> None:
        return None

    def bring_to_front(hwnd: int) -> None:
        return None


def raise_new_zotero_windows(before: set[int], stop: threading.Event, timeout: float = 20.0) -> None:
    """Holt Fenster von Zotero nach vorne, die nach ``before`` erschienen sind (den Dialog).

    Erscheint kein neues Fenster, wird nach zwei Sekunden das Zotero-Hauptfenster nach vorne geholt –
    manche Dialoge hängen am Hauptfenster."""
    raised: set[int] = set()
    waited = 0.0
    while not stop.is_set() and waited < timeout:
        try:
            current = zotero_windows()
            new = [w for w in current if w not in before and w not in raised]
            for w in new:
                bring_to_front(w)
                raised.add(w)
            if not raised and waited >= 2.0 and current:
                bring_to_front(current[0])
                raised.add(current[0])
        except Exception:  # noqa: BLE001 - nur Komfort, darf nie stören
            return
        stop.wait(0.4)
        waited += 0.4


def start_dialog_watch() -> threading.Event:
    """Startet die Überwachung; das zurückgegebene Event beendet sie."""
    stop = threading.Event()
    if sys.platform == "win32":
        before = set(zotero_windows())
        threading.Thread(target=raise_new_zotero_windows, args=(before, stop), name="zotero-dialog-focus",
                         daemon=True).start()
    return stop
