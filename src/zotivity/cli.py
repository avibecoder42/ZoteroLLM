"""Kommandozeile: zotivity serve | index | search | ask | keys | status | plugin | mcp"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import logging.handlers
import os
import sys
import threading
import webbrowser

from zotivity import __version__, paths


def setup_logging(quiet: bool = False, level: str = "INFO") -> None:
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(paths.log_dir() / "zotivity.log", maxBytes=5_000_000, backupCount=3,
                                             encoding="utf-8")
    ]
    if not quiet and sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers,
                        force=True)
    for noisy in ("httpx", "httpcore", "httpx2", "openai", "anthropic", "google_genai", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def cmd_serve(args) -> None:
    import uvicorn

    from zotivity.engine import Engine
    from zotivity.server.app import create_app
    from zotivity.service import clear_state, read_state, write_state

    engine = Engine()
    settings = engine.settings
    host = args.host or settings.server.host
    port = args.port or settings.server.port

    existing = read_state()
    if existing and _alive(existing):
        print(f"Zotivity läuft bereits: {existing['url']}")
        if args.open:
            webbrowser.open(existing["url"])
        return

    server: uvicorn.Server | None = None

    def request_exit():
        if server is not None:
            server.should_exit = True

    app = create_app(engine, on_exit=request_exit, exit_after_minutes=getattr(args, "exit_with_zotero", None))
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False,
                            log_config=None, timeout_graceful_shutdown=5)
    server = uvicorn.Server(config)
    write_state(host, port)
    url = f"http://{host}:{port}/"
    logging.getLogger("zotivity").info("Zotivity %s läuft auf %s", __version__, url)
    if not args.quiet:
        print(f"Zotivity {__version__} läuft auf {url}  (Beenden mit Strg+C)")
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.run()
    finally:
        clear_state()


def _alive(state: dict) -> bool:
    import httpx

    try:
        return httpx.get(state["url"] + "api/plugin/info", timeout=2, trust_env=False).status_code == 200
    except httpx.HTTPError:
        return False


def _print_job(job) -> None:
    last = ""
    while job.status in ("queued", "running"):
        d = job.as_dict()
        line = f"[{d['phase']}] {d['done']}/{d['total'] or '?'} {d['message'][:70]}"
        if d["counters"].get("chunks_embedded"):
            line += f" | eingebettet: {d['counters']['chunks_embedded']}"
        if line != last:
            print(line, flush=True)
            last = line
        threading.Event().wait(2)
    print(f"Status: {job.status}" + (f" – {job.error}" if job.error else ""))
    if job.result:
        print(json.dumps(job.result, ensure_ascii=False, indent=2, default=str))


def cmd_index(args) -> None:
    from zotivity.engine import Engine
    from zotivity.index.indexer import Indexer

    engine = Engine()
    indexer = Indexer(engine)
    cols = args.collection or None
    job = engine.jobs.start("index", "Indexierung", lambda j: indexer.run(
        j, sync=not args.no_sync, collections=cols, retry_errors=args.retry_errors, full_sync=args.full),
        group="index")
    try:
        _print_job(job)
    except KeyboardInterrupt:
        job.cancel()
        print("Abbruch …")
        while job.status == "running":
            threading.Event().wait(0.5)


def cmd_search(args) -> None:
    from zotivity.engine import Engine
    from zotivity.rag.sources import build_sources
    from zotivity.retrieval import Searcher

    engine = Engine()
    hits = Searcher(engine).search(args.query, k=args.k)
    for s in build_sources(engine.store, hits, 0, 10**9):
        print(f"[{s.n}] {s.citation} – {s.title[:70]} ({s.page_text})")
        print("    " + s.text[:300].replace("\n", " "))
        if s.att_key:
            print("    " + s.as_dict().get("zotero_pdf", ""))


def cmd_ask(args) -> None:
    from zotivity.engine import Engine
    from zotivity.rag import AskOptions, ChatService

    engine = Engine()
    for ev in ChatService(engine).ask(args.question, None, AskOptions(search_only=args.search_only)):
        t = ev["type"]
        if t == "delta":
            print(ev["text"], end="", flush=True)
        elif t == "status":
            print(f"… {ev['text']}", file=sys.stderr)
        elif t == "queries":
            print("Suchanfragen: " + " | ".join(ev["queries"]), file=sys.stderr)
        elif t == "sources":
            sources = ev["sources"]
        elif t in ("error", "warning"):
            print(f"\n[{t}] {ev.get('message') or ev.get('text')}", file=sys.stderr)
        elif t == "done":
            print("\n\nQuellen:")
            for s in sources:
                print(f"[{s['n']}] {s['citation']}: {s['title'][:80]} (S. {s['page_label']})")


def cmd_keys(args) -> None:
    from zotivity.catalog import PROVIDERS
    from zotivity.keystore import get_store

    store = get_store()
    if args.action == "list":
        print(f"Schlüsselspeicher: {store.backend_info()}")
        for p in PROVIDERS.values():
            if p.needs_key or p.id == "openai_compatible":
                print(f"  {p.id:20s} {store.masked(p.id) or '–':12s} {store.source(p.id) or ''}")
        return
    if not args.provider or args.provider not in PROVIDERS:
        sys.exit(f"Anbieter angeben: {', '.join(PROVIDERS)}")
    if args.action == "set":
        key = getpass.getpass(f"API-Schlüssel für {args.provider} (Eingabe unsichtbar): ")
        store.set(args.provider, key)
        print(f"Gespeichert: {store.masked(args.provider)}")
    elif args.action == "delete":
        print("Gelöscht." if store.delete(args.provider) else "Kein Schlüssel vorhanden.")


def cmd_status(args) -> None:
    from zotivity.engine import Engine
    from zotivity.service import read_state

    engine = Engine()
    state = read_state()
    print(f"Zotivity {__version__}")
    print(f"  Dienst:      {state['url'] if state and _alive(state) else 'läuft nicht'}")
    print(f"  Daten:       {paths.data_dir()}")
    print(f"  Einstellung: {paths.settings_file()}")
    z = engine.zotero().status()
    print(f"  Zotero:      {'läuft' if z['running'] else 'nicht erreichbar'}"
          f"{' (Version ' + z['version'] + ')' if z.get('version') else ''}"
          f"{'' if z['local_api'] else ' – lokale API aus'}")
    emb = engine.embedding_status()
    print(f"  Embedding:   {emb.get('provider')}:{emb.get('model')} {'ok' if emb['ok'] else emb.get('error')}")
    print(f"  Index:       {json.dumps(engine.store.stats(emb.get('space')), ensure_ascii=False)}")


def cmd_plugin(args) -> None:
    from zotivity.plugin_build import build_xpi

    path = build_xpi()
    print(f"Plugin erstellt: {path}")


def cmd_mcp(args) -> None:
    from zotivity.mcp_server import run

    run()


def service_main() -> None:
    """Einstiegspunkt ohne Konsole (pythonw): startet den Dienst."""
    setup_logging(quiet=True)
    cmd_serve(argparse.Namespace(host=None, port=None, quiet=True, open=False, exit_with_zotero=None))


def main(argv: list[str] | None = None) -> None:
    # Unter pythonw (ohne Konsole) gibt es kein stdout/stderr
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    parser = argparse.ArgumentParser(prog="zotivity", description="Semantische Suche und KI-Fragen für Zotero")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--log-level", default=os.environ.get("ZOTIVITY_LOG", "INFO"))
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("serve", help="Dienst mit Weboberfläche starten")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--quiet", action="store_true", help="keine Konsolenausgabe")
    p.add_argument("--open", action="store_true", help="Oberfläche im Browser öffnen")
    p.add_argument("--exit-with-zotero", type=int, metavar="MIN",
                   help="beenden, wenn Zotero so viele Minuten geschlossen ist (vom Plugin gesetzt)")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("index", help="Bibliothek abgleichen und indexieren")
    p.add_argument("--collection", action="append",
                   help="lib:KEY, z. B. users/0:ABCD1234, oder lib:* für eine ganze Bibliothek (mehrfach möglich)")
    p.add_argument("--full", action="store_true", help="alle Metadaten neu aus Zotero laden")
    p.add_argument("--no-sync", action="store_true", help="ohne Abgleich mit Zotero")
    p.add_argument("--retry-errors", action="store_true", help="fehlgeschlagene Dokumente erneut versuchen")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("search", help="Textstellen suchen (ohne LLM)")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=10)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("ask", help="Frage an die Bibliothek stellen")
    p.add_argument("question")
    p.add_argument("--search-only", action="store_true")
    p.set_defaults(fn=cmd_ask)

    p = sub.add_parser("keys", help="API-Schlüssel verwalten (verschlüsselt im Schlüsselspeicher des Systems)")
    p.add_argument("action", choices=["list", "set", "delete"])
    p.add_argument("provider", nargs="?")
    p.set_defaults(fn=cmd_keys)

    p = sub.add_parser("status", help="Zustand anzeigen")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("plugin", help="Zotero-Plugin (.xpi) erstellen")
    p.set_defaults(fn=cmd_plugin)

    p = sub.add_parser("mcp", help="MCP-Server (stdio) für Claude Desktop u. a.")
    p.set_defaults(fn=cmd_mcp)

    args = parser.parse_args(argv)
    setup_logging(quiet=getattr(args, "quiet", False) or args.cmd == "mcp", level=args.log_level.upper())
    args.fn(args)
