"""Eingebaute Laufzeit für Embedding-Modelle: llama.cpp (``llama-server``) als Hilfsprozess.

Wie Ollama startet Zotivity für das gewählte GGUF-Modell einen lokalen llama-server und spricht ihn über
HTTP an. Der Prozess

- lauscht nur auf 127.0.0.1 an einem freien Port und verlangt einen zufälligen Schlüssel (nur Zotivity
  kann ihn nutzen), greift nie aufs Netz zu (``--offline``);
- läuft mit niedriger Priorität, damit der Rechner beim Indexieren bedienbar bleibt;
- hängt unter Windows an einem Job-Objekt: Endet Zotivity (auch durch Absturz), endet er mit;
- wird nach einigen Minuten ohne Anfrage beendet und gibt den Arbeitsspeicher frei.

Mitgeliefert wird das offizielle Windows-Paket von llama.cpp mit allen Prozessor-Varianten (ggml-cpu-*.dll);
llama.cpp wählt beim Start die schnellste, die der Prozessor kann – auch ohne AVX2.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np

from zotivity import paths
from zotivity.embeddings.base import EmbeddingError

log = logging.getLogger(__name__)

EXE_NAME = "llama-server.exe" if sys.platform == "win32" else "llama-server"
START_TIMEOUT = 300.0
_TOO_LONG = re.compile(r"\((\d+) tokens\)")


# -- Programmdateien finden --------------------------------------------------------------------------
def server_candidates() -> list[Path]:
    out = []
    if os.environ.get("ZOTIVITY_LLAMA_DIR"):
        out.append(Path(os.environ["ZOTIVITY_LLAMA_DIR"]))
    if getattr(sys, "frozen", False):
        out.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "llama")
        out.append(Path(sys.executable).parent / "llama")
    # Entwicklung: von packaging/fetch_llama.py geholt
    out.append(Path(__file__).resolve().parents[3] / "build" / "vendor" / "llama")
    return out


def find_server() -> Path | None:
    for folder in server_candidates():
        exe = folder / EXE_NAME
        if exe.is_file():
            return exe
    return None


@lru_cache(maxsize=4)
def server_version(exe: str) -> str:
    try:
        with _quiet_errors():
            proc = subprocess.Popen([exe, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,  # noqa: S603
                                    stdin=subprocess.DEVNULL, text=True, creationflags=_NO_WINDOW, env=_clean_env())
        out, err = proc.communicate(timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"build (\d+)", (out or "") + (err or ""))
    return f"b{m.group(1)}" if m else ""


_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_BELOW_NORMAL = 0x00004000 if sys.platform == "win32" else 0
_DLL_NOT_FOUND = -1073741515  # 0xC0000135
_error_mode_lock = threading.Lock()


@contextmanager
def _quiet_errors():
    """Keine Systemfenster des Hilfsprozesses (fehlende DLL, Absturzmeldung): Zotivity meldet selbst.
    Der Fehlermodus wird beim Start vererbt; für den eigenen Prozess gilt danach wieder der alte."""
    if sys.platform != "win32":
        yield
        return
    import ctypes

    k32 = ctypes.windll.kernel32
    with _error_mode_lock:
        old = k32.SetErrorMode(0x0001 | 0x0002 | 0x8000)  # FAILCRITICALERRORS | NOGPFAULTERRORBOX | NOOPENFILEERRORBOX
        try:
            yield
        finally:
            k32.SetErrorMode(old)


def _clean_env() -> dict:
    # Eigene LLAMA_ARG_*-Variablen des Systems dürfen die Einstellungen nicht verändern
    return {k: v for k, v in os.environ.items() if not k.upper().startswith(("LLAMA_", "HF_"))}


def cpu_features() -> dict:
    """AVX2/AVX-512 des Prozessors (nur Anzeige – llama.cpp wählt seine Variante selbst)."""
    if sys.platform == "win32":
        import ctypes

        present = ctypes.windll.kernel32.IsProcessorFeaturePresent
        return {"avx2": bool(present(40)), "avx512": bool(present(41))}
    try:
        flags = Path("/proc/cpuinfo").read_text(errors="ignore")
        return {"avx2": " avx2" in flags, "avx512": " avx512f" in flags}
    except OSError:
        return {"avx2": None, "avx512": None}


# -- Windows: Kindprozesse an Zotivity binden -----------------------------------------------------------
class _JobObject:
    def __init__(self):
        self.handle = None
        if sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rt", "wt", "ot")]

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        handle = k32.CreateJobObjectW(None, None)
        if not handle:
            return
        info = Extended()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if k32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.handle = handle
            self._k32 = k32

    def assign(self, proc: subprocess.Popen) -> None:
        if self.handle:
            self._k32.AssignProcessToJobObject(self.handle, int(proc._handle))  # type: ignore[attr-defined]


def peak_memory(pid: int) -> int | None:
    """Höchster Arbeitsspeicher (Bytes) eines Prozesses – nur Windows."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000 | 0x0010, False, pid)
    if not h:
        return None
    try:
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        if not k32.K32GetProcessMemoryInfo(wintypes.HANDLE(h), ctypes.byref(c), c.cb):
            return None
        return int(c.PeakWorkingSetSize)
    finally:
        k32.CloseHandle(wintypes.HANDLE(h))


# -- Ein Serverprozess je Modell ------------------------------------------------------------------------
@dataclass(frozen=True)
class ServerSpec:
    model_path: str
    pooling: str = ""
    ctx: int = 2048  # Tokens je Abschnitt
    parallel: int = 4  # gleichzeitig verarbeitete Abschnitte
    threads: int | None = None

    @property
    def key(self) -> tuple:
        return (self.model_path, self.pooling, self.ctx, self.parallel, self.threads)


class TooLong(Exception):
    def __init__(self, tokens: int | None):
        super().__init__(tokens)
        self.tokens = tokens


class LlamaServer:
    def __init__(self, spec: ServerSpec, exe: Path, log_path: Path):
        self.spec = spec
        self.exe = exe
        self.log_path = log_path
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self._token = secrets.token_urlsafe(24)
        self._http = httpx.Client(timeout=httpx.Timeout(600.0, connect=5.0), trust_env=False,
                                  headers={"Authorization": f"Bearer {self._token}"})
        self._start_lock = threading.Lock()
        self.busy = 0
        self.last_used = time.time()
        self.started_at = 0.0

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def command(self) -> list[str]:
        s = self.spec
        cmd = [str(self.exe), "-m", s.model_path, "--embedding", "--host", "127.0.0.1", "--port", str(self.port),
               "--no-webui", "--offline", "-lv", "2", "-c", str(s.ctx * s.parallel), "-b", str(s.ctx),
               "-ub", str(s.ctx), "-np", str(s.parallel)]
        if s.pooling:
            cmd += ["--pooling", s.pooling]
        if s.threads:
            cmd += ["-t", str(s.threads)]
        return cmd

    def ensure_started(self, runtime: LlamaRuntime) -> None:
        with self._start_lock:
            if self.alive():
                return
            self._start(runtime)

    def _start(self, runtime: LlamaRuntime) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        env = _clean_env()
        env["LLAMA_API_KEY"] = self._token
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.log_path, "wb") as logfile, _quiet_errors():  # der Prozess erbt eine Kopie des Handles
                self.proc = subprocess.Popen(self.command(), stdout=logfile, stderr=subprocess.STDOUT,  # noqa: S603
                                             stdin=subprocess.DEVNULL, env=env, cwd=str(self.exe.parent),
                                             creationflags=_NO_WINDOW | _BELOW_NORMAL)
        except OSError as e:
            raise EmbeddingError(f"Die eingebaute Laufzeit konnte nicht starten: {e}") from e
        runtime.job.assign(self.proc)
        self.started_at = time.time()
        deadline = time.time() + START_TIMEOUT
        while time.time() < deadline:
            if self.proc.poll() is not None:
                if self.proc.returncode in (_DLL_NOT_FOUND, _DLL_NOT_FOUND & 0xFFFFFFFF):
                    raise EmbeddingError("Eine Programmdatei der eingebauten Laufzeit fehlt. Bitte Zotivity neu "
                                         "installieren (Virenscanner prüfen, falls er Dateien entfernt hat).")
                raise EmbeddingError(f"Die eingebaute Laufzeit ist beim Laden des Modells abgebrochen: {self.log_tail()}")
            try:
                if self._http.get(f"{self.base_url}/health", timeout=2.0).status_code == 200:
                    log.info("llama-server bereit: %s (Port %d, %.1f s)", Path(self.spec.model_path).name, self.port,
                             time.time() - self.started_at)
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        self.stop()
        raise EmbeddingError("Die eingebaute Laufzeit hat das Modell nicht rechtzeitig geladen.", transient=True)

    def log_tail(self, n: int = 600) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""
        lines = [l for l in text.splitlines() if l.strip()]
        return " | ".join(lines[-4:])[-n:] or "keine Meldung"

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def peak_memory(self) -> int | None:
        return peak_memory(self.proc.pid) if self.alive() else None

    # -- Anfragen ----------------------------------------------------------------------------------
    def _post(self, texts: list[str]) -> tuple[np.ndarray, int]:
        try:
            r = self._http.post(f"{self.base_url}/v1/embeddings", json={"input": texts, "encoding_format": "float"})
        except httpx.TransportError as e:
            raise EmbeddingError("Die eingebaute Laufzeit antwortet nicht.", transient=True) from e
        if r.status_code != 200:
            try:
                err = r.json().get("error") or {}
            except ValueError:
                err = {}
            msg = str(err.get("message") or r.text[:300])
            if "too large" in msg or "exceed" in msg:
                m = _TOO_LONG.search(msg)
                raise TooLong(err.get("n_prompt_tokens") or (int(m.group(1)) if m else None))
            raise EmbeddingError(f"Fehler der eingebauten Laufzeit ({r.status_code}): {msg}",
                                 transient=r.status_code >= 500)
        data = r.json()
        vecs = [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
        return np.asarray(vecs, dtype=np.float32), int((data.get("usage") or {}).get("prompt_tokens") or 0)

    def embed(self, texts: list[str]) -> tuple[np.ndarray, int]:
        """Vektoren und Anzahl verarbeiteter Tokens. Zu lange Texte werden gekürzt."""
        try:
            return self._post(texts)
        except TooLong:
            if len(texts) > 1:
                parts = [self.embed([t]) for t in texts]
                return np.vstack([p[0] for p in parts]), sum(p[1] for p in parts)
        try:
            return self._post([self._shorten(texts[0])])
        except TooLong as e:
            raise EmbeddingError(f"Ein Textabschnitt ist zu lang für das Modell ({e.tokens} Tokens).") from e

    def _shorten(self, text: str) -> str:
        limit = self.spec.ctx
        for _ in range(6):
            try:
                n = len(self._http.post(f"{self.base_url}/tokenize", json={"content": text}).json().get("tokens", []))
            except (httpx.HTTPError, ValueError):
                n = 0
            if n and n <= limit - 4:
                return text
            ratio = (limit - 8) / n if n else 0.7
            text = text[: max(1, int(len(text) * min(ratio, 0.95) * 0.97))]
        return text


class LlamaRuntime:
    def __init__(self, max_servers: int = 2):
        self.max_servers = max_servers
        self.keep_alive = 600.0
        self.job = _JobObject()
        self._servers: dict[tuple, LlamaServer] = {}
        self._lock = threading.Lock()
        self._reaper: threading.Thread | None = None
        self._stop = threading.Event()
        self._atexit = False

    # -- Auskunft ------------------------------------------------------------------------------------
    def info(self) -> dict:
        exe = find_server()
        return {"available": exe is not None, "path": str(exe.parent) if exe else "",
                "version": server_version(str(exe)) if exe else "", **cpu_features(),
                "running": [{"model": Path(s.spec.model_path).name, "port": s.port, "since": s.started_at}
                            for s in list(self._servers.values()) if s.alive()]}

    # -- Server holen ----------------------------------------------------------------------------------
    def server(self, spec: ServerSpec) -> LlamaServer:
        exe = find_server()
        if exe is None:
            raise EmbeddingError("Die eingebaute Laufzeit (llama.cpp) fehlt in dieser Installation. "
                                 "Bitte Zotivity neu installieren oder einen anderen Embedding-Anbieter wählen.")
        with self._lock:
            srv = self._servers.get(spec.key)
            if srv is None:
                idle = sorted((s for s in self._servers.values() if s.busy == 0), key=lambda s: s.last_used)
                while len(self._servers) >= self.max_servers and idle:
                    victim = idle.pop(0)
                    victim.stop()
                    self._servers.pop(victim.spec.key, None)
                name = re.sub(r"[^\w.-]+", "_", Path(spec.model_path).stem)[:60]
                srv = LlamaServer(spec, exe, paths.log_dir() / f"llama-{name}.log")
                self._servers[spec.key] = srv
            srv.busy += 1
            self._ensure_reaper()
        try:
            srv.ensure_started(self)
        except Exception:
            with self._lock:
                srv.busy -= 1
            raise
        return srv

    def release(self, srv: LlamaServer) -> None:
        with self._lock:
            srv.busy = max(0, srv.busy - 1)
            srv.last_used = time.time()

    def embed(self, spec: ServerSpec, texts: list[str]) -> tuple[np.ndarray, int]:
        srv = self.server(spec)
        try:
            try:
                return srv.embed(texts)
            except EmbeddingError as e:
                if not e.transient or srv.proc is None:
                    raise
                try:  # Abgestürzt? Der Prozess braucht nach dem Verbindungsabbruch einen Moment zum Beenden
                    srv.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    raise e from None
                log.warning("llama-server unerwartet beendet (Code %s) – Neustart: %s", srv.proc.returncode,
                            srv.log_tail())
                srv.ensure_started(self)
                return srv.embed(texts)
        finally:
            self.release(srv)

    # -- Aufräumen -------------------------------------------------------------------------------------
    def _ensure_reaper(self) -> None:
        if self._reaper and self._reaper.is_alive():
            return
        self._stop.clear()
        self._reaper = threading.Thread(target=self._reap_loop, name="llama-reaper", daemon=True)
        self._reaper.start()
        if not self._atexit:
            atexit.register(self.stop_all)
            self._atexit = True

    def _reap_loop(self) -> None:
        while not self._stop.wait(15):
            self.reap()

    def reap(self, now: float | None = None) -> int:
        now = now or time.time()
        stopped = 0
        with self._lock:
            for key, srv in list(self._servers.items()):
                if srv.busy == 0 and (not srv.alive() or now - srv.last_used > self.keep_alive):
                    srv.stop()
                    self._servers.pop(key, None)
                    stopped += 1
        return stopped

    def stop_model(self, model_path: str) -> None:
        with self._lock:
            for key, srv in list(self._servers.items()):
                if srv.spec.model_path == model_path:
                    srv.stop()
                    self._servers.pop(key, None)

    def stop_all(self) -> None:
        self._stop.set()
        with self._lock:
            for srv in self._servers.values():
                srv.stop()
            self._servers.clear()


_runtime: LlamaRuntime | None = None
_runtime_lock = threading.Lock()


def get_runtime() -> LlamaRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = LlamaRuntime()
        return _runtime
