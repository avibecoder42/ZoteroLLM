"""HTTP für die Datenquellen: httpx mit Wiederholung bei 429/5xx (wie ``request`` in litsearch.py).

Tests übergeben einen ``httpx.MockTransport`` und eine ``sleep``-Funktion, die nicht wartet – so laufen sie ohne Netz.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from . import __version__
from .errors import SourceError

RETRY_STATUS = (429, 500, 502, 503, 504)


class Http:
    def __init__(self, transport: httpx.BaseTransport | None = None, timeout: float = 90.0,
                 sleep: Callable[[float], None] = time.sleep, user_agent: str = f"litsearch/{__version__}"):
        self.sleep = sleep
        self.client = httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0), transport=transport,
                                   headers={"User-Agent": user_agent}, follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, url: str, *, retries: int = 5, check: bool = True, **kw) -> httpx.Response:
        """check=False: Fehlerstatus (>= 400, ausser 429/5xx) zurückgeben statt SourceError auslösen."""
        host = urlsplit(url).netloc or url
        for attempt in range(retries):
            try:
                r = self.client.request(method, url, **kw)
            except httpx.TransportError as e:
                if attempt < retries - 1:
                    self.sleep(2 ** (attempt + 1))
                    continue
                raise SourceError(f"{host} ist nicht erreichbar: {e}") from None
            if r.status_code in RETRY_STATUS and attempt < retries - 1:
                self.sleep(_retry_after(r) or 2 ** (attempt + 1))
                continue
            if r.headers.get("Backoff"):  # Zotero bittet um eine Pause
                self.sleep(_seconds(r.headers["Backoff"]))
            if check and r.status_code >= 400:
                raise SourceError(f"{method} {url.split('?')[0]} -> HTTP {r.status_code}: {r.text[:300]}", r.status_code)
            return r
        raise SourceError(f"{host}: keine Antwort nach {retries} Versuchen")  # pragma: no cover - Schleife endet vorher

    def get_json(self, url: str, **kw):
        return self.request("GET", url, **kw).json()


def _seconds(value: str) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _retry_after(r: httpx.Response) -> float:
    return _seconds(r.headers.get("Retry-After", ""))
