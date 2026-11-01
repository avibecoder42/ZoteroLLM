"""Zeitschätzung und Kurztest für eingebaute Embedding-Modelle.

- **Vor dem Download** (geschätzt): Messwert des Modells auf dem Referenzrechner des Katalogs, umgerechnet mit
  einem Rechentest von gut einer Sekunde auf diesem Rechner. Sobald hier ein Modell gemessen wurde, dient diese
  Messung als genauerer Umrechnungsfaktor.
- **Nach dem Download** (gemessen): Kurztest mit dem Testsatz ``data/embedding_benchmark.json`` – Tempo,
  Arbeitsspeicher und ob sprachübergreifende Suchfragen die richtige Stelle finden.
- **Beim Indexieren** zeigt die Indexierung den laufenden Messwert.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import sys
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

from zotivity import paths
from zotivity.embeddings import model_catalog, model_store
from zotivity.embeddings.model_catalog import ModelEntry

BENCH_FILE = model_catalog.DATA_DIR / "embedding_benchmark.json"
# 100 Seiten ≈ 200 Abschnitte à rund 400 Tokens
TOKENS_PER_100_PAGES = 80_000
# Tokens/s × Millionen Rechenparameter auf dem Referenzrechner (für Modelle ohne eigenen Messwert)
REF_THROUGHPUT = 120_000
SCORE_MAX_AGE = 30 * 86400


def cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def machine_file() -> Path:
    return paths.data_dir() / "machine.json"


def _measure_gflops(seconds: float = 1.2) -> float:
    """Rechentest: Matrixprodukte (float32) über alle Kerne, bestes von mehreren Durchgängen."""
    rng = np.random.default_rng(0)
    a = rng.random((1024, 1024), dtype=np.float32)
    b = a.T.copy()
    a @ b
    best, end = 0.0, time.perf_counter() + seconds
    while time.perf_counter() < end:
        t0 = time.perf_counter()
        for _ in range(4):
            a @ b
        best = max(best, 4 * 2 * 1024**3 / (time.perf_counter() - t0) / 1e9)
    return round(best, 1)


def cpu_score(force: bool = False) -> dict:
    """Rechenleistung dieses Rechners (zwischengespeichert, alle 30 Tage neu gemessen)."""
    path = machine_file()
    if not force and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - data.get("measured_at", 0) < SCORE_MAX_AGE and data.get("cpu") == cpu_name():
                return data
        except (OSError, ValueError):
            pass
    data = {"cpu": cpu_name(), "cores": os.cpu_count(), "gflops": _measure_gflops(), "measured_at": time.time()}
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def machine_factor(installed: dict | None = None, score: dict | None = None) -> dict:
    """Wie schnell dieser Rechner im Vergleich zum Referenzrechner ist."""
    installed = installed if installed is not None else model_store.installed()
    ratios = []
    for mid, rec in installed.items():
        test = rec.get("test") or {}
        entry = model_catalog.get(mid)
        if test.get("tok_per_s") and entry and entry.reference.tok_per_s and test.get("cpu") == cpu_name():
            ratios.append(test["tok_per_s"] / entry.reference.tok_per_s)
    if ratios:
        return {"factor": round(statistics.median(ratios), 3), "source": "measured", "models": len(ratios)}
    ref = (model_catalog.current().reference or {}).get("cpu_score") or 0
    score = score or cpu_score()
    if ref and score.get("gflops"):
        return {"factor": round(score["gflops"] / ref, 3), "source": "cpu_test", "gflops": score["gflops"]}
    return {"factor": 1.0, "source": "reference"}


def estimate(entry: ModelEntry, factor: float, test: dict | None = None) -> dict:
    """Tokens/s und Minuten pro 100 Seiten: gemessen (Kurztest) oder geschätzt."""
    if test and test.get("tok_per_s") and test.get("cpu") == cpu_name():
        tps, source = float(test["tok_per_s"]), "measured"
    elif entry.reference.tok_per_s:
        tps, source = entry.reference.tok_per_s * factor, "estimated"
    else:
        compute = entry.compute_m or (entry.params_m * 0.6 if entry.params_m else None)
        if not compute:
            return {"tok_per_s": None, "minutes_per_100_pages": None, "source": "unknown"}
        tps, source = REF_THROUGHPUT / compute * factor, "estimated"
    return {"tok_per_s": round(tps), "minutes_per_100_pages": round(TOKENS_PER_100_PAGES / tps / 60, 1),
            "source": source}


def ram_estimate(entry: ModelEntry, test: dict | None = None) -> dict:
    if test and test.get("ram_mb"):
        return {"mb": test["ram_mb"], "source": "measured"}
    if entry.reference.ram_mb:
        return {"mb": entry.reference.ram_mb, "source": "reference"}
    return {"mb": round(entry.file.bytes / 2**20 * 1.15 + 150), "source": "estimated"}


@lru_cache(maxsize=1)
def bench_set() -> dict:
    return json.loads(BENCH_FILE.read_text(encoding="utf-8"))


def short_test(embedder, job=None) -> dict:
    """Kurztest mit dem eingebauten Embedder (BuiltinEmbedder): Tempo, Speicher, Suchqualität."""
    from zotivity.embeddings.llama_runtime import get_runtime

    bench = bench_set()
    passages = bench["passages"]
    docs = [p["text"] for p in passages]
    ids = [p["id"] for p in passages]
    runtime = get_runtime()
    if job:
        job.update(phase="Kurztest", message="Modell wird geladen …", total=4, done=0)
    t0 = time.time()
    srv = runtime.server(embedder.spec())
    try:
        load_s = time.time() - t0
        embedder.embed_documents(docs[:2])  # aufwärmen
        if job:
            job.check()
            job.update(message="Tempo wird gemessen …", done=1)
        best_tps, dvecs = 0.0, None
        for i in range(2):  # alle Texte in einem Aufruf; das schnellere von zwei Malen zählt
            t = time.time()
            dvecs = embedder.embed_documents(docs)
            elapsed = time.time() - t
            if embedder.last_tokens:
                best_tps = max(best_tps, embedder.last_tokens / max(elapsed, 1e-6))
            if job:
                job.check()
                job.update(done=2 + i)
        if job:
            job.update(message="Suchqualität wird geprüft …")
        qvecs = embedder.embed_queries([q["text"] for q in bench["queries"]])
        dn = dvecs / np.linalg.norm(dvecs, axis=1, keepdims=True)
        qn = qvecs / np.linalg.norm(qvecs, axis=1, keepdims=True)
        sims = qn @ dn.T
        hits, margins = 0, []
        for i, q in enumerate(bench["queries"]):
            j = ids.index(q["expect"])
            row = sims[i].copy()
            right = float(row[j])
            row[j] = -9
            margins.append(right - float(row.max()))
            hits += int(right > float(row.max()))
        ram = srv.peak_memory()
    finally:
        runtime.release(srv)
    if job:
        job.update(done=4, message="Fertig")
    tps = round(best_tps) if best_tps else None
    return {
        "tok_per_s": tps,
        "minutes_per_100_pages": round(TOKENS_PER_100_PAGES / tps / 60, 1) if tps else None,
        "top1": hits, "queries": len(bench["queries"]),
        "margin": round(float(np.mean(margins)), 3), "margin_min": round(float(np.min(margins)), 3),
        "ram_mb": round(ram / 2**20) if ram else None, "load_s": round(load_s, 1),
        "dim": int(dvecs.shape[1]) if dvecs is not None else None,
        "ok": hits >= len(bench["queries"]) - 2,
        "cpu": cpu_name(), "measured_at": time.time(),
    }
