"""REST-Schnittstelle ``/api/research/…`` für die Oberfläche (Konzept 3.4, „Schnittstellen“).

``install(app, service)`` hängt Router und Fehlerbehandlung an eine bestehende FastAPI-App – in der eigenständigen
App wie später in ZotLLM. Sicherheit (nur 127.0.0.1, Host-Prüfung, Header gegen CSRF) gehört der App-Hülle.
Endpunkte sind synchron: FastAPI ruft sie aus einem Thread-Pool auf, Suchen blockieren die Oberfläche nicht.
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .errors import ResearchError
from .export import collection_paths
from .service import ResearchService
from .sources.ris import decode

PREFIX = "/api/research"


class ProjectIn(BaseModel):
    title: str | None = None
    question: str | None = None
    description: str | None = None
    criteria_in: str | None = None
    criteria_out: str | None = None
    target_library: str | None = None
    target_name: str | None = None
    zotero_backend: str | None = None
    folder_map: list[dict[str, Any]] | None = None
    prefilters: list[dict[str, Any]] | None = None
    settings: dict[str, Any] | None = None


class BlocksIn(BaseModel):
    blocks: list[dict[str, Any]]


class AiBlocksIn(BaseModel):
    blocks: list[dict[str, Any]] | None = None
    focus: dict[str, Any] | None = None     # {name, kind, terms, hint}: nur diesen Block neu vorschlagen


class BuildIn(BaseModel):
    blocks: list[dict[str, Any]] | None = None


class TranslateIn(BaseModel):
    string: str
    to: str = "openalex"


class QueryIn(BaseModel):
    name: str
    source: str
    string: str
    limits: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


class QueryUpdate(BaseModel):
    name: str | None = None
    string: str | None = None
    limits: dict[str, Any] | None = None
    note: str | None = None


class TextFile(BaseModel):
    filename: str = ""
    content: str = ""
    content_b64: str = ""  # Rohdaten (RIS aus Ovid oft in Windows-1252) – die Kodierung erkennt der Dienst

    def raw(self) -> str | bytes:
        return base64.b64decode(self.content_b64) if self.content_b64 else self.content

    def text(self) -> str:
        raw = self.raw()
        return decode(raw) if isinstance(raw, bytes) else raw


class QueryFilesIn(BaseModel):
    files: list[TextFile]
    source: str = "pubmed"
    limits: dict[str, Any] = Field(default_factory=dict)


class CountIn(BaseModel):
    source: str
    string: str
    limits: dict[str, Any] = Field(default_factory=dict)


class RunIn(BaseModel):
    max_records: int | None = None


class ImportIn(TextFile):
    source: str = "ris"
    name: str = ""
    string: str = ""
    hits: int | None = None


class MoveFolderIn(BaseModel):
    from_slot: int
    to_slot: int


class ConfirmIn(BaseModel):
    confirm: bool = False


class BackendIn(BaseModel):
    backend: str | None = None


class AiFoldersIn(BaseModel):
    parent: str = ""                        # Pfad der übergeordneten Sammlung, z. B. „test“
    lib: str | None = None                  # sonst die Zielbibliothek des Projekts
    backend: str | None = None


class AiEstimateIn(BaseModel):
    kind: str                               # sources | blocks | folders
    blocks: list[dict[str, Any]] | None = None
    parent: str = ""


class CollectionsIn(BaseModel):
    paths: list[str]
    confirm: bool = False                   # ohne ausdrückliche Bestätigung wird nichts angelegt


class DecisionIn(BaseModel):
    record_id: int
    status: str
    folder: int | None = None
    reason: str = ""
    borderline: bool | None = None          # None: Kennzeichen vom bisherigen Entscheid übernehmen
    borderline_reason: str | None = None
    ai_shown: bool | None = None            # war der KI-Vorschlag sichtbar (KI-Schalter)?
    method: str = "card"                    # card | list


class BulkDecisionsIn(BaseModel):
    items: list[dict[str, Any]]             # je {record_id, status, folder?, reason?}
    ai_shown: bool | None = None
    method: str = "list"


class BorderlineIn(BaseModel):
    record_id: int
    on: bool = True
    reason: str = ""


class ReviewIn(BaseModel):
    record_ids: list[int]
    verdict: str                            # restore | borderline | exclude
    rule_id: str | None = None


class TargetsIn(BaseModel):
    targets: list[str]


class AbstractsIn(BaseModel):
    limit: int = 25
    retry: bool = False                     # nur Quellen, die beim letzten Mal ausgefallen sind


class KeyPapersIn(BaseModel):
    text: str = ""


class AiScreenIn(BaseModel):
    limit: int = 20
    scope: str = "open"                     # open | borderline | all
    redo: str = ""                          # "" nur neue | failed: auch ohne gültige Antwort | all: alle neu
    since: str | None = None                # Beginn des Durchgangs (aus der ersten Antwort)


class ExportIn(BaseModel):
    backend: str | None = None
    confirm: bool = False
    crossref: bool = True


def make_router(svc: ResearchService) -> APIRouter:
    r = APIRouter(prefix=PREFIX, tags=["research"])

    @r.get("/info")
    def info():
        return svc.info()

    @r.get("/ai/status")
    def ai_status():
        return svc.ai_status()

    @r.post("/projects/{pid}/ai/screening")
    def ai_screening(pid: int, body: AiScreenIn):
        return svc.ai_screen(pid, body.limit, body.scope, body.redo, body.since)

    @r.get("/projects/{pid}/ai/plan")
    def ai_plan(pid: int):
        return svc.ai_plan(pid)

    @r.post("/projects/{pid}/ai/sources")
    def ai_sources(pid: int):
        return svc.ai_sources(pid)

    @r.post("/projects/{pid}/ai/blocks")
    def ai_blocks(pid: int, body: AiBlocksIn):
        return svc.ai_blocks(pid, body.blocks, body.focus)

    @r.get("/sources/suggest")
    def suggest_sources(disciplines: str = ""):
        return {"sources": svc.suggest_sources([d for d in disciplines.split(",") if d])}

    # -- Projekte ------------------------------------------------------------------------------------
    @r.get("/projects")
    def projects():
        return {"projects": svc.list_projects()}

    @r.post("/projects")
    def create_project(body: ProjectIn):
        return svc.create_project(body.model_dump(exclude_none=True))

    @r.get("/projects/{pid}")
    def get_project(pid: int):
        return svc.get_project(pid)

    @r.put("/projects/{pid}")
    def update_project(pid: int, body: ProjectIn):
        return svc.update_project(pid, body.model_dump(exclude_none=True))

    @r.delete("/projects/{pid}")
    def delete_project(pid: int):
        svc.delete_project(pid)
        return {"ok": True}

    @r.get("/projects/{pid}/summary")
    def summary(pid: int):
        svc.store.project(pid)
        return svc.summary(pid)

    # -- Suchstrategie ---------------------------------------------------------------------------------
    @r.put("/projects/{pid}/blocks")
    def set_blocks(pid: int, body: BlocksIn):
        return {"blocks": svc.set_blocks(pid, body.blocks)}

    @r.post("/projects/{pid}/build")
    def build(pid: int, body: BuildIn):
        return svc.build(pid, body.blocks)

    @r.post("/translate")
    def translate(body: TranslateIn):
        return svc.translate(body.string, body.to)

    @r.get("/projects/{pid}/terms")
    def terms(pid: int):
        return svc.terms(pid)

    # -- Suchstrings und Suchen ------------------------------------------------------------------------
    @r.get("/projects/{pid}/queries")
    def queries(pid: int):
        return {"queries": svc.queries(pid)}

    @r.post("/projects/{pid}/queries")
    def add_query(pid: int, body: QueryIn):
        return svc.add_query(pid, body.name, body.source, body.string, body.limits, body.note)

    @r.post("/projects/{pid}/queries/import")
    def import_queries(pid: int, body: QueryFilesIn):
        files = [{"filename": f.filename, "content": f.text()} for f in body.files]
        return {"queries": svc.import_query_files(pid, files, body.source, body.limits)}

    @r.put("/queries/{qid}")
    def update_query(qid: int, body: QueryUpdate):
        return svc.update_query(qid, body.model_dump(exclude_none=True))

    @r.delete("/queries/{qid}")
    def delete_query(qid: int):
        svc.delete_query(qid)
        return {"ok": True}

    @r.get("/queries/{qid}/versions")
    def versions(qid: int):
        return {"versions": svc.store.query_versions(qid)}

    @r.post("/queries/{qid}/count")
    def count_query(qid: int):
        return svc.count_query(qid)

    @r.post("/queries/{qid}/run")
    def run_query(qid: int, body: RunIn):
        return svc.run_query(qid, body.max_records)

    @r.post("/queries/{qid}/translate")
    def translate_query(qid: int, body: TargetsIn):
        return {"queries": svc.translate_query(qid, body.targets)}

    @r.post("/count")
    def count(body: CountIn):
        return svc.count(body.source, body.string, body.limits)

    @r.get("/projects/{pid}/runs")
    def runs(pid: int):
        return {"runs": svc.runs(pid)}

    @r.post("/projects/{pid}/import")
    def import_ris(pid: int, body: ImportIn):
        return svc.import_ris(pid, body.filename, body.raw(), body.source, body.name, body.string, body.hits)

    # -- Pool und Screening ----------------------------------------------------------------------------
    @r.get("/projects/{pid}/pool")
    def pool(pid: int, source: str = "", query: str = "", year_from: int | None = None, year_to: int | None = None,
             journal: str = "", lang: str = "", text: str = "", status: str = "", show_hidden: bool = False,
             rule: str = ""):
        return svc.pool(pid, source=source, query=query, year_from=year_from, year_to=year_to, journal=journal,
                        lang=lang, text=text, status=status, show_hidden=show_hidden, rule=rule)

    @r.get("/projects/{pid}/records/{rid}")
    def record(pid: int, rid: int):
        return svc.store.record(pid, rid)

    @r.post("/projects/{pid}/folders/move")
    def move_folder(pid: int, body: MoveFolderIn):
        return svc.move_folder(pid, body.from_slot, body.to_slot)

    @r.post("/projects/{pid}/pool/reset")
    def reset_pool(pid: int, body: ConfirmIn):
        return svc.reset_pool(pid, body.confirm)

    @r.post("/projects/{pid}/zotero/match")
    def zotero_match(pid: int, body: BackendIn):
        return svc.zotero_match(pid, body.backend)

    @r.post("/projects/{pid}/review")
    def review(pid: int, body: ReviewIn):
        return svc.review(pid, body.record_ids, body.verdict, body.rule_id)

    @r.post("/projects/{pid}/abstracts")
    def abstracts(pid: int, body: AbstractsIn):
        return svc.fetch_abstracts(pid, max(1, min(body.limit, 100)), retry=body.retry)

    @r.get("/projects/{pid}/recall")
    def recall(pid: int):
        return svc.recall(pid)

    @r.put("/projects/{pid}/key-papers")
    def key_papers(pid: int, body: KeyPapersIn):
        return svc.set_key_papers(pid, body.text)

    @r.get("/projects/{pid}/screening")
    def screening(pid: int, status: str = "open"):
        return svc.queue(pid, status)

    @r.post("/projects/{pid}/decisions")
    def decide(pid: int, body: DecisionIn):
        return svc.decide(pid, body.record_id, body.status, body.folder, body.reason,
                          borderline=body.borderline, borderline_reason=body.borderline_reason,
                          ai_shown=body.ai_shown, method=body.method)

    @r.post("/projects/{pid}/borderline")
    def borderline(pid: int, body: BorderlineIn):
        return svc.mark_borderline(pid, body.record_id, body.on, body.reason)

    @r.post("/projects/{pid}/decisions/bulk")
    def decide_bulk(pid: int, body: BulkDecisionsIn):
        return svc.decide_bulk(pid, body.items, body.ai_shown, body.method)

    @r.post("/projects/{pid}/decisions/undo")
    def undo(pid: int):
        return {"undone": svc.undo(pid)}

    # -- Übergabe ---------------------------------------------------------------------------------------
    @r.get("/projects/{pid}/export/zotero")
    def export_plan(pid: int, backend: str | None = None):
        return svc.export_plan(pid, backend)

    @r.post("/projects/{pid}/export/zotero")
    def export(pid: int, body: ExportIn):
        return svc.export(pid, body.backend, confirm=body.confirm, crossref=body.crossref)

    @r.get("/projects/{pid}/protocol")
    def protocol(pid: int, kind: str = "md"):
        text, filename, mime = svc.protocol(pid, kind)
        return Response(text, media_type=f"{mime}; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Filename": filename})

    # -- Zotero -----------------------------------------------------------------------------------------
    @r.get("/zotero/status")
    def zotero_status(backend: str = "web"):
        return svc.zotero_port(backend).status()

    @r.get("/zotero/libraries")
    def zotero_libraries(backend: str = "web"):
        return {"libraries": svc.zotero_port(backend).libraries()}

    @r.get("/zotero/collections")
    def zotero_collections(lib: str, backend: str = "web"):
        cols = svc.zotero_port(backend).collections(lib)
        return {"collections": cols, "paths": sorted(collection_paths(cols))}

    @r.get("/zotero/tree")
    def zotero_tree(lib: str, backend: str = "web"):
        return svc.zotero_tree(backend, lib)

    @r.post("/projects/{pid}/zotero/collections")
    def create_collections(pid: int, body: CollectionsIn):
        return svc.create_collections(pid, body.paths, body.confirm)

    @r.post("/projects/{pid}/ai/estimate")
    def ai_estimate(pid: int, body: AiEstimateIn):
        return svc.ai_estimate(pid, body.kind, body.blocks, body.parent)

    @r.post("/projects/{pid}/ai/folders")
    def ai_folders(pid: int, body: AiFoldersIn):
        return svc.ai_folders(pid, body.parent, body.lib, body.backend)

    @r.post("/zotero/authorize")
    def zotero_authorize(body: BackendIn):
        port = svc.zotero_port(body.backend or "local")
        authorize = getattr(port, "authorize", None)
        if not authorize:
            raise ResearchError("Für diesen Zugang braucht es keine Freigabe.")
        return {"ok": bool(authorize())}

    return r


def install(app: FastAPI, svc: ResearchService) -> None:
    app.include_router(make_router(svc))

    @app.exception_handler(ResearchError)
    async def _research_error(_: Request, e: ResearchError):
        return JSONResponse({"detail": str(e), "kind": e.kind}, status_code=e.status)
