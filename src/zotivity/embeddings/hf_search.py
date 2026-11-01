"""Embedding-Modelle auf Hugging Face nach Namen suchen (GGUF) und als eigenes Modell übernehmen.

Anders als bei Ollama sind frei gesuchte Modelle nicht fertig eingerichtet. Darum prüft Zotivity vor dem
Download, ob llama.cpp die Architektur als Embedding-Modell ausführen kann (Hugging Face liest sie aus den
GGUF-Dateien aus), und schlägt Präfixe und Pooling aus der Beschreibung des Originalmodells vor
(Sentence-Transformers-Konfiguration). Solche Modelle gelten als „nicht geprüft“.
"""

from __future__ import annotations

import re

import httpx

from zotivity import __version__
from zotivity.embeddings import model_catalog
from zotivity.embeddings.base import EmbeddingError
from zotivity.embeddings.model_catalog import ModelEntry

API = "https://huggingface.co/api"
# Architekturen, die llama.cpp als Embedding-Modell (bidirektional) ausführt
EMBED_ARCHS = {"bert", "nomic-bert", "nomic-bert-moe", "jina-bert-v2", "jina-bert-v3", "modern-bert", "neo-bert",
               "gemma-embedding", "gemma-embedding2", "t5encoder", "eurobert", "roberta", "xlm-roberta"}
# Sprachmodell-Architekturen: als Embedding-Modell nutzbar, wenn das Modell dafür trainiert ist (Pooling „last“)
DECODER_ARCHS = {"qwen3", "qwen2", "gemma3", "gemma2", "llama", "mistral", "qwen3moe", "phi3", "granite"}
_QUANT = re.compile(r"(?i)[._-]((?:UD-)?(?:I?Q\d(?:_[A-Z0-9]+)*)|F16|BF16|F32)(?:-\d+-of-\d+)?\.gguf$")
_REF = re.compile(r"^(?:https?://)?(?:www\.)?(?:huggingface\.co|hf\.co)/(?P<repo>[\w.-]+/[\w.-]+?)"
                  r"(?::(?P<quant>[\w.-]+))?(?:/(?:blob|resolve|tree)/(?P<rev>[\w.-]+)(?:/(?P<file>[^?#]+))?)?/?(?:[?#].*)?$")
_REPO = re.compile(r"^(?P<repo>[\w.-]+/[\w.-]+?)(?::(?P<quant>[\w.-]+))?$")


def _client() -> httpx.Client:
    return httpx.Client(follow_redirects=True, trust_env=True, timeout=httpx.Timeout(20.0, connect=10.0),
                        headers={"User-Agent": f"Zotivity/{__version__}"})


def parse_ref(text: str) -> dict | None:
    """Adresse oder Name eines Repositorys: „owner/repo“, „hf.co/owner/repo:Q8_0“, Link zu einer Datei."""
    t = (text or "").strip()
    m = _REF.match(t) or (_REPO.match(t) if "/" in t and " " not in t else None)
    if not m:
        return None
    d = m.groupdict()
    return {"repo": d["repo"], "file": d.get("file"), "quant": d.get("quant")}


def quant_of(name: str) -> str:
    m = _QUANT.search(name)
    return m.group(1).upper() if m else ""


def support(arch: str, name: str = "") -> str:
    """supported: Embedding-Architektur; decoder: Sprachmodell-Bauweise (nur echte Embedding-Modelle);
    unknown: llama.cpp kennt sie möglicherweise nicht."""
    arch = (arch or "").lower()
    if arch in EMBED_ARCHS:
        return "supported"
    if arch in DECODER_ARCHS:
        return "decoder" if "embed" in name.lower() or "harrier" in name.lower() else "not_embedding"
    return "unknown"


def _is_embedding(m: dict) -> bool:
    name = m.get("id", "").lower()
    pipe = m.get("pipeline_tag") or (m.get("cardData") or {}).get("pipeline_tag") or ""
    tags = set(m.get("tags") or [])
    if "rerank" in name or pipe in ("text-classification", "text-generation", "image-text-to-text"):
        return "embed" in name and "rerank" not in name
    arch = ((m.get("gguf") or {}).get("architecture") or "").lower()
    return (pipe in ("feature-extraction", "sentence-similarity") or "sentence-transformers" in tags
            or "text-embeddings-inference" in tags or arch in EMBED_ARCHS or "embed" in name)


def _catalog_id_for(repo: str) -> str | None:
    for m in model_catalog.all_models():
        if m.source.repo.lower() == repo.lower():
            return m.id
    return None


def _summary(m: dict) -> dict:
    g = m.get("gguf") or {}
    card = m.get("cardData") or {}
    arch = g.get("architecture") or ""
    lic = card.get("license") or next((t.split(":", 1)[1] for t in m.get("tags") or [] if t.startswith("license:")), "")
    return {"repo": m["id"], "downloads": m.get("downloads") or 0, "likes": m.get("likes") or 0,
            "updated": m.get("lastModified") or "", "license": lic, "architecture": arch,
            "support": support(arch, m["id"]), "params_m": round(g["total"] / 1e6) if g.get("total") else None,
            "context": g.get("context_length"), "gated": bool(m.get("gated")),
            "catalog_id": _catalog_id_for(m["id"])}


def search(query: str, http: httpx.Client | None = None, limit: int = 30) -> dict:
    query = (query or "").strip()
    if len(query) < 2:
        return {"query": query, "results": []}
    client = http or _client()
    try:
        ref = parse_ref(query)
        if ref and ("huggingface.co" in query or "hf.co" in query or query.count("/") == 1):
            try:
                return {"query": query, "results": [_summary(_get(client, f"{API}/models/{ref['repo']}",
                                                                   {"expand[]": EXPAND}))], "direct": True}
            except EmbeddingError:
                if "huggingface.co" in query or "hf.co" in query:
                    raise
        params = [("search", query), ("filter", "gguf"), ("sort", "downloads"), ("direction", "-1"),
                  ("limit", str(min(100, limit * 3)))] + [("expand[]", e) for e in EXPAND]
        found = _get(client, f"{API}/models", params)
    finally:
        if http is None:
            client.close()
    results = [_summary(m) for m in found if _is_embedding(m)][:limit]
    return {"query": query, "results": results}


EXPAND = ["downloads", "likes", "lastModified", "pipeline_tag", "tags", "gguf", "cardData", "gated"]


def _get(client: httpx.Client, url: str, params=None):
    try:
        r = client.get(url, params=params)
    except httpx.TransportError as e:
        raise EmbeddingError("Hugging Face ist nicht erreichbar – besteht eine Internetverbindung?", transient=True) from e
    if r.status_code == 404:
        raise EmbeddingError("Dieses Modell gibt es auf Hugging Face nicht (oder es ist privat).")
    if r.status_code >= 400:
        raise EmbeddingError(f"Hugging Face meldet Fehler {r.status_code}.", transient=r.status_code >= 500)
    return r.json()


def _raw_json(client: httpx.Client, repo: str, path: str) -> dict | None:
    try:
        r = client.get(f"https://huggingface.co/{repo}/raw/main/{path}")
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, dict) else None
    except (httpx.HTTPError, ValueError):
        pass
    return None


def suggest_settings(repo: str, client: httpx.Client) -> dict:
    """Präfixe und Pooling aus der Sentence-Transformers-Konfiguration des Originalmodells."""
    out = {"query_prefix": "", "document_prefix": "", "pooling": "", "source": ""}
    st = _raw_json(client, repo, "config_sentence_transformers.json")
    prompts = (st or {}).get("prompts") or {}
    if isinstance(prompts, dict) and prompts:
        out["query_prefix"] = next((prompts[k] for k in ("query", "search_query", "retrieval_query",
                                                         "web_search_query", "Retrieval-query") if prompts.get(k)), "")
        out["document_prefix"] = next((prompts[k] for k in ("document", "passage", "search_document",
                                                            "retrieval_document", "Retrieval-document")
                                       if prompts.get(k)), "")
        out["source"] = repo
    pool = _raw_json(client, repo, "1_Pooling/config.json") or {}
    if pool.get("pooling_mode_cls_token"):
        out["pooling"] = "cls"
    elif pool.get("pooling_mode_lasttoken"):
        out["pooling"] = "last"
    elif pool.get("pooling_mode_mean_tokens"):
        out["pooling"] = "mean"
    if pool and not out["source"]:
        out["source"] = repo
    return out


def model_detail(repo: str, http: httpx.Client | None = None) -> dict:
    """Dateien (GGUF-Varianten mit Grösse und Prüfsumme), Lizenz, Architektur und Vorschläge zu Präfixen."""
    client = http or _client()
    try:
        m = _get(client, f"{API}/models/{repo}", {"blobs": "true", "expand[]": EXPAND + ["siblings", "sha"]})
        files = []
        for s in m.get("siblings") or []:
            name = s.get("rfilename", "")
            if not name.lower().endswith(".gguf") or "mmproj" in name.lower() or "/" in name:
                continue
            lfs = s.get("lfs") or {}
            if not lfs.get("sha256") or not s.get("size"):
                continue
            files.append({"name": name, "bytes": int(s["size"]), "sha256": lfs["sha256"], "quant": quant_of(name)})
        order = ["Q8_0", "F16", "BF16", "Q6_K", "Q5_K_M", "Q4_K_M"]
        files.sort(key=lambda f: (order.index(f["quant"]) if f["quant"] in order else 99, f["bytes"]))
        card = m.get("cardData") or {}
        base = card.get("base_model")
        base = (base[0] if isinstance(base, list) and base else base) or ""
        sugg = suggest_settings(base, client) if isinstance(base, str) and "/" in base else None
        if not sugg or not sugg["source"]:
            sugg = suggest_settings(repo, client)
    finally:
        if http is None:
            client.close()
    info = _summary(m)
    return {**info, "revision": m.get("sha") or "main", "base_model": base, "files": files,
            "recommended": files[0]["name"] if files else None, "suggested": sugg,
            "pipeline": m.get("pipeline_tag") or ""}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-.")
    return s[:90] or "modell"


def make_user_entry(detail: dict, file_name: str, query_prefix: str = "", document_prefix: str = "",
                    pooling: str = "") -> ModelEntry:
    f = next((x for x in detail["files"] if x["name"] == file_name), None)
    if f is None:
        raise EmbeddingError("Diese Datei gibt es im Repository nicht.")
    if detail.get("gated"):
        raise EmbeddingError("Dieses Modell verlangt auf Hugging Face eine Anmeldung oder Lizenzbestätigung – "
                             "das unterstützt Zotivity nicht.")
    if detail.get("support") == "not_embedding":
        raise EmbeddingError("Das ist ein Sprachmodell, kein Embedding-Modell.")
    repo = detail["repo"]
    name = repo.split("/", 1)[1]
    for suffix in ("-GGUF", "-gguf", "_GGUF", ".GGUF"):
        name = name.removesuffix(suffix)
    model_id = "hf-" + slug(f"{repo.split('/')[0]}-{name}-{f['quant'] or 'gguf'}")
    # Sprachmodell-Bauweise braucht Zwischenspeicher je Token: kürzere Abschnitte halten den Speicherbedarf klein
    ctx = 1024 if detail.get("support") == "decoder" else 2048
    if detail.get("context"):
        ctx = min(ctx, int(detail["context"]))
    return ModelEntry.model_validate({
        "id": model_id, "name": f"{name} ({f['quant']})" if f["quant"] else name,
        "vendor": repo.split("/")[0], "group": model_catalog.USER_GROUP,
        "params_m": detail.get("params_m"), "context": detail.get("context"),
        "license": detail.get("license") or "", "model_url": f"https://huggingface.co/{repo}",
        "source": {"repo": repo, "revision": detail.get("revision") or "main", "official": False},
        "file": {"name": f["name"], "quant": f["quant"], "bytes": f["bytes"], "sha256": f["sha256"]},
        "runtime": {"pooling": pooling, "query_prefix": query_prefix, "document_prefix": document_prefix,
                    "ctx": max(128, ctx)},
        "aliases": [detail.get("base_model")] if detail.get("base_model") else [],
        "user": True, "origin": "user",
    })
