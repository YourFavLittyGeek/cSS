"""uengine/transfer/locks.py - Phase 1b: per-study and per-destination locks (in-process AND cross-process).

TransferLocks(project).hold(keys, timeout) acquires every key (sorted -> no lock-order deadlock) with
  * a threading.Lock per key (threads of this process), and
  * fcntl.flock(LOCK_EX) on <project>/app_data/locks/<sha1(key)>.lock (other Percival processes).
Keys: "study:<code>" (one writing job per study) and "dst:<canonical destination path>" (one writer per destination
file). The lock files are empty markers; they are never deleted while the app runs (deleting a flock file would break
mutual exclusion) and contain only the key text for diagnosis.

study_processing_active(project, code) reads app_data/patients.json (read only): a study whose pipeline run is
running / starting / paused must not be archived, synced, staged over or cleaned.
"""
import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from typing import Dict, Iterable, List

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

from ..safety import PathPolicy, canon

_THREAD_LOCKS: Dict[str, threading.Lock] = {}
_REGISTRY_LOCK = threading.Lock()
PROCESSING_STATES = {"running", "starting", "paused"}


class LockTimeout(TimeoutError):
    pass


def study_key(code: str) -> str:
    return f"study:{code}"


def dst_key(path: str) -> str:
    return f"dst:{canon(path).lower()}"          # case-insensitive volumes: one lock per name regardless of case


class TransferLocks:
    def __init__(self, project_base: str, vault_root=None):
        self.dir = os.path.join(os.path.abspath(project_base), "app_data", "locks")
        PathPolicy(project_base, vault_root).check_write_target(os.path.join(self.dir, "x.lock"))
        os.makedirs(self.dir, exist_ok=True)

    def _file(self, key: str) -> str:
        return os.path.join(self.dir, hashlib.sha1(key.encode()).hexdigest() + ".lock")

    @contextmanager
    def hold(self, keys: Iterable[str], timeout: float = 30.0):
        keys = sorted(set(keys))
        held_threads: List[threading.Lock] = []
        held_fds: List[int] = []
        deadline = time.monotonic() + timeout
        try:
            for k in keys:
                with _REGISTRY_LOCK:
                    tl = _THREAD_LOCKS.setdefault(k, threading.Lock())
                if not tl.acquire(timeout=max(0.0, deadline - time.monotonic())):
                    raise LockTimeout(f"{k} is held by another transfer in this process")
                held_threads.append(tl)
                fd = os.open(self._file(k), os.O_RDWR | os.O_CREAT, 0o644)
                held_fds.append(fd)
                if fcntl is not None:
                    while True:
                        try:
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except BlockingIOError:
                            if time.monotonic() > deadline:
                                raise LockTimeout(f"{k} is held by another Percival process")
                            time.sleep(0.02)
                try:
                    os.ftruncate(fd, 0)
                    os.write(fd, k.encode()[:4000])
                except OSError:
                    pass
            yield keys
        finally:
            for fd in reversed(held_fds):
                try:
                    if fcntl is not None:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
            for tl in reversed(held_threads):
                tl.release()


def _probe(self, key: str) -> bool:
    """True if nobody (no thread of this process, no other process) holds key right now. Takes and releases at once."""
    with _REGISTRY_LOCK:
        tl = _THREAD_LOCKS.setdefault(key, threading.Lock())
    if not tl.acquire(blocking=False):
        return False
    try:
        fd = os.open(self._file(key), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if fcntl is None:
                return True
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            fcntl.flock(fd, fcntl.LOCK_UN)
            return True
        finally:
            os.close(fd)
    finally:
        tl.release()


TransferLocks.probe = _probe


def study_processing_active(project_base: str, code: str) -> bool:
    p = os.path.join(project_base, "app_data", "patients.json")
    try:
        with open(p) as f:
            pats = json.load(f)
    except (OSError, ValueError):
        return False
    return any(isinstance(x, dict) and x.get("code") == code and x.get("status") in PROCESSING_STATES for x in pats or [])
