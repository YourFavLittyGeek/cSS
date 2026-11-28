"""Crash- and corruption-safe JSON state files for the app (2026-11-28, audit finding: data-loss path in jload/jsave).

The old behaviour (css_app.jload / jsave):
  jload: ANY read error (truncated file, empty file, invalid JSON, permission error, a file being written at that moment) returned the
         default ([] / {}), and the next jsave then OVERWROTE patients.json / settings.json with that empty default - silent data loss.
  jsave: one shared "<name>.tmp" for every thread (a live race was seen in launcher.log), no fsync, no backup.

Now:
  load():  missing file -> default (a genuinely new project). A file that EXISTS but cannot be read or parsed is retried (transient), then the
           last good backup "<name>.bak" is used if it parses; the unreadable original is preserved (copied to app_data/corrupt/). If nothing
           readable exists the file is BLOCKED: load returns the default so the app can start, but save() refuses to write that file until
           the problem is resolved (no empty default can ever replace the real file). Every problem is recorded in PROBLEMS.
  save():  refused for a blocked file; otherwise write to a unique temporary file (pid + thread), flush + fsync, keep the previous good version
           as "<name>.bak", atomic os.replace, fsync the directory. One lock per process serialises writers.
"""
import json, os, shutil, threading, time

LOCK = threading.RLock()
PROBLEMS = {}            # name -> dict(at, error, action, preserved)
RETRIES = 3
RETRY_WAIT_S = 0.05


class BlockedError(RuntimeError):
    pass


def _parse(p):
    with open(p, "rb") as f: raw = f.read()
    if not raw.strip(): raise ValueError("empty file")
    return json.loads(raw.decode("utf-8"))


def _preserve(d, name, p):
    q = os.path.join(d, "corrupt"); os.makedirs(q, exist_ok=True)
    dst = os.path.join(q, f"{name}.{time.strftime('%Y%m%d_%H%M%S')}.{os.getpid()}")
    try: shutil.copy2(p, dst); return dst
    except Exception: return None


def load(d, name, default):
    """-> parsed content, or default (missing file, or blocked - see module doc)"""
    p = os.path.join(d, name)
    with LOCK:
        if not os.path.exists(p):
            if os.path.exists(p + ".bak"):                      # the file vanished but a good backup exists: never start empty
                try:
                    v = _parse(p + ".bak"); PROBLEMS[name] = dict(at=time.strftime("%Y-%m-%d %H:%M:%S"), error="file missing", action="restored from backup", preserved=None)
                    return v
                except Exception: pass
            return default
        err = None
        for i in range(RETRIES):
            try:
                v = _parse(p); PROBLEMS.pop(name, None); return v
            except Exception as e:
                err = f"{type(e).__name__}: {e}"; time.sleep(RETRY_WAIT_S * (i + 1))
        kept = _preserve(d, name, p)
        try:
            v = _parse(p + ".bak")
            PROBLEMS[name] = dict(at=time.strftime("%Y-%m-%d %H:%M:%S"), error=err, action="loaded the last good backup (.bak); the unreadable file was preserved", preserved=kept)
            return v
        except Exception:
            PROBLEMS[name] = dict(at=time.strftime("%Y-%m-%d %H:%M:%S"), error=err, action="BLOCKED: not readable and no readable backup - nothing will be written to this file until it is repaired", preserved=kept, blocked=True)
            return default


def blocked(name): return bool((PROBLEMS.get(name) or {}).get("blocked"))


def save(d, name, obj):
    """atomic, fsynced write with a backup of the previous version; raises BlockedError for a blocked file"""
    p = os.path.join(d, name)
    with LOCK:
        if blocked(name): raise BlockedError(f"{name} is blocked (unreadable at start-up): it is not overwritten - {PROBLEMS[name]['error']}")
        data = json.dumps(obj, indent=1, default=str).encode("utf-8")
        tmp = f"{p}.tmp.{os.getpid()}.{threading.get_ident()}"
        try:
            with open(tmp, "wb") as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            if os.path.exists(p):
                try: _parse(p); shutil.copy2(p, p + ".bak")                # keep the previous version only if it is itself good
                except Exception: pass
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except OSError: pass
        try:
            fd = os.open(d, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        except (OSError, AttributeError): pass
        if name in PROBLEMS and not PROBLEMS[name].get("blocked"): PROBLEMS[name]["resolved_by_save"] = time.strftime("%Y-%m-%d %H:%M:%S")


def unblock(d, name, by, reason):
    """explicit, recorded decision to start this file afresh (the unreadable original stays preserved in app_data/corrupt/)"""
    with LOCK:
        if not blocked(name): return dict(ok=False, error="not blocked")
        if not by or not reason: return dict(ok=False, error="a person and a reason are required")
        PROBLEMS[name].update(blocked=False, unblocked_by=by, unblock_reason=reason, unblocked_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        return dict(ok=True)
