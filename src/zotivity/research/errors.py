"""Fehler der Recherche. ``kind`` hilft der Oberfläche, passende Hinweise zu zeigen."""

from __future__ import annotations


class ResearchError(RuntimeError):
    status = 400

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind


class NotFound(ResearchError):
    status = 404

    def __init__(self, message: str):
        super().__init__(message, "not_found")


class SourceError(ResearchError):
    """Eine Datenquelle (PubMed, OpenAlex, Crossref, Zotero-Web-API) hat mit einem Fehler geantwortet."""

    status = 502

    def __init__(self, message: str, http_status: int | None = None):
        super().__init__(message, "source")
        self.http_status = http_status


class ZoteroWriteRefused(ResearchError):
    """Schreiben nach Zotero ohne ausdrückliche Bestätigung oder ohne Freigabe."""

    status = 409

    def __init__(self, message: str, kind: str = "zotero_confirm"):
        super().__init__(message, kind)
