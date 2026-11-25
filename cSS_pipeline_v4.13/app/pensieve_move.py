"""Pensieve move (2026-11-25, user's decision): after the expert's final review a study's processed files go to the external
Pensieve drive (<vault>/studies/<code>/<version>/...), and come back to the Mac automatically when the study is opened again.

What moves:  raw/<code>/ (converted MRI), data/<code>_*, synthseg/<code>_*, work/<code>_*, subjects/<code>/, logs/<code>_*
What is copied but stays on the Mac: review/<code>_* (calls, scores, final records - tiny; lists, reports and scores keep working)
Marker:      review/<code>_pensieve.json = the source of truth (state, version, every moved file with size + SHA-256)

Safety (narrow exception to the Phase 0 protection of raw/ and data/, agreed with the user):
  - the copy is a normal journaled transfer job (Transfer Center shows it): write-once version folder, verified copy;
  - a Mac file is deleted ONLY after its Pensieve copy was read back and has the same SHA-256 as the Mac file;
  - a file that could not be verified stays on the Mac (listed in kept_local);
  - restore writes only files that are missing on the Mac (never overwrites) and checks every SHA-256 against the marker;
  - only this study's own files under raw/<code>/ and data/<code>_* are opened for the restore (RestorePolicy).
Every version stays on Pensieve (archives are write-once); a re-review after a restore archives a new version.

Used by the app (automatic move after the final review, restore before a re-run) and by the reviewer (restore on open)."""
import glob
import hashlib
import json
import os
import shutil
import threading
import time

SCHEMA = 1
LOCK = threading.Lock()            # one move / restore at a time in this process
STATUS = {}                        # code -> dict(state, label, error, t) for the GUI (this process)


def marker_path(B, code): return os.path.join(B, "review", f"{code}_pensieve.json")


def read_marker(B, code):
    try:
        with open(marker_path(B, code)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_marker(B, code, m):
    p = marker_path(B, code); tmp = f"{p}.tmp-{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(m, f, indent=1)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)


AWAY = ("in_pensieve", "deleting")   # 'deleting' = marker written BEFORE the first Mac file is removed (a crash mid-way is restorable)


def state(B, code):
    """'on_mac' (never moved or restored), 'in_pensieve', 'copied' (copy only, Mac files kept), or a running state"""
    s = STATUS.get(code)
    if s and s.get("state") in ("moving", "restoring"): return s["state"]
    m = read_marker(B, code)
    st = (m or {}).get("state", "on_mac")
    return "in_pensieve" if st == "deleting" else st


def in_pensieve(B, code):
    m = read_marker(B, code)
    return bool(m and m.get("state") in AWAY)


def busy():
    """a move or restore is running in this process (the app waits for it before quitting)"""
    return LOCK.locked()


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(4 * 2 ** 20), b""): h.update(b)
    return h.hexdigest()


def _files_under(B, top):
    """every regular file under a project-relative top (file or folder) -> project-relative paths; links are not followed.
    raw/<code>/<MOD>/_dicom (temporary DICOM copies, deleted by source_cleanup) is never moved."""
    a = os.path.join(B, top)
    if os.path.islink(a): return []
    if os.path.isfile(a): return [top]
    out = []
    for root, dirs, files in os.walk(a):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d)) and d != "_dicom"]
        for n in files:
            q = os.path.join(root, n)
            if os.path.isfile(q) and not os.path.islink(q): out.append(os.path.relpath(q, B))
    return sorted(out)


def moved_tops(B, code):
    """project-relative files / folders that MOVE (deleted on the Mac after verification)"""
    tops = []
    for d in ("raw", "subjects"):
        if os.path.isdir(os.path.join(B, d, code)): tops.append(os.path.join(d, code))
    for d in ("data", "synthseg", "work", "logs"):
        tops += sorted(os.path.relpath(p, B) for p in glob.glob(os.path.join(B, d, f"{code}_*")) if not os.path.islink(p))
    return tops


def copied_tops(B, code):
    """review files: copied to Pensieve, kept on the Mac (the marker itself is written after the copy)"""
    mk = os.path.basename(marker_path(B, code))
    return sorted(os.path.relpath(p, B) for p in glob.glob(os.path.join(B, "review", f"{code}_*"))
                  if os.path.isfile(p) and not os.path.islink(p) and os.path.basename(p) != mk and ".tmp-" not in p)


def newest_final(B, code):
    """mtime of the newest final-review record of any reviewer (0 if none)"""
    ps = glob.glob(os.path.join(B, "review", f"{code}_final_*.json")) + glob.glob(os.path.join(B, "review", f"{code}_final.json"))
    return max((os.path.getmtime(p) for p in ps), default=0.0)


def drive_ready(vault):
    """(ok, reason) - Pensieve connected and archivable (exFAT: guarded commit)"""
    if not vault: return False, "no Pensieve drive configured"
    try:
        from uengine.storage.vault_check import verify_vault
        v = verify_vault(vault)
    except Exception as e:
        return False, f"Pensieve check failed: {e}"
    if v.get("verdict") != "archive_ok": return False, "; ".join(v.get("reasons") or [f"Pensieve: {v.get('verdict')}"])
    return True, ""


def last_activity(B, code):
    """newest change of the study's review files (calls, events, final records): the reviewer writes them on every decision"""
    mk = os.path.basename(marker_path(B, code))
    ts = [os.path.getmtime(q) for q in glob.glob(os.path.join(B, "review", f"{code}_*")) if os.path.basename(q) != mk and ".tmp-" not in q]
    return max(ts, default=0.0)


def due(B, p, grace_s=300, now=None, since=0.0):
    """a finished, reviewed study whose newest final review is older than the grace time and newer than its last move.
    since: only reviews saved after this time (the moment the feature was first switched on) move automatically - studies
    reviewed before the update move only when the user asks (Settings > Pensieve > "Move earlier reviewed studies now")."""
    code = p.get("code", "")
    if p.get("status") != "done" or not code: return False
    fin = newest_final(B, code)
    if not fin or (now or time.time()) - fin < grace_s or fin <= float(since or 0): return False
    if (now or time.time()) - last_activity(B, code) < grace_s: return False     # still being read / corrected
    m = read_marker(B, code) or {}
    if m.get("state") in AWAY: return False
    return fin > float(m.get("final_mtime") or 0)


def _set(code, st, label="", error=""):
    STATUS[code] = dict(state=st, label=label, error=error, t=time.time())


def move(B, vault, code, delete_local=True):
    """copy the study to Pensieve (journaled job, verified), then delete the verified Mac copies of the moved files.
    Returns dict(ok, version, moved_bytes, kept_local, error)."""
    from uengine.safety import validate_study_code
    from uengine.transfer.service import TransferService
    validate_study_code(code)
    if not LOCK.acquire(blocking=False): return dict(ok=False, error="another Pensieve move or restore is running")
    try:
        ok, why = drive_ready(vault)
        if not ok: return dict(ok=False, error=why)
        if in_pensieve(B, code): return dict(ok=False, error=f"{code} is already in Pensieve")
        fin = newest_final(B, code)
        mv, cp = moved_tops(B, code), copied_tops(B, code)
        if not mv and not cp: return dict(ok=False, error=f"{code}: nothing to move")
        ver = time.strftime("r%Y%m%dT%H%M%S")
        rel_root = os.path.join("studies", code, ver); root = os.path.join(vault, rel_root)
        _set(code, "moving", "copying to Pensieve")
        svc = TransferService(B, vault)
        try:
            items = [(os.path.join(B, rel), os.path.join(root, rel)) for t in mv for rel in _files_under(B, t)]
            items += [(os.path.join(B, t), os.path.join(root, t)) for t in cp]
            rep = svc.transfer("archive", items, study_id=code)
        finally:
            svc.close()
        if not rep.get("ok"):
            err = "; ".join(rep.get("errors") or []) or rep.get("state") or "the copy did not complete"
            _set(code, "failed", "", f"copy to Pensieve failed: {err} - nothing was deleted on the Mac")
            return dict(ok=False, error=STATUS[code]["error"], job_id=rep.get("job_id"))
        _set(code, "moving", "checking every copied file")
        files, kept, review = [], [], []
        for t in mv:
            for rel in _files_under(B, t):
                src, dst = os.path.join(B, rel), os.path.join(root, rel)
                try:
                    s1 = _sha(src); s2 = _sha(dst) if os.path.isfile(dst) else None
                except OSError as e:
                    kept.append(dict(rel=rel, reason=f"not readable: {e}")); continue
                if s1 != s2: kept.append(dict(rel=rel, reason="the Pensieve copy is missing or differs")); continue
                files.append(dict(rel=rel, size=os.path.getsize(src), sha256=s1))
        for t in cp:
            dst = os.path.join(root, t)
            if os.path.isfile(dst): review.append(t)
        m = dict(schema=SCHEMA, code=code, state="copied", version=ver, vault_rel=rel_root, archived_at=time.time(),
                 final_mtime=fin, files=files, review_files=review, kept_local=kept, job_id=rep.get("job_id"),
                 versions=((read_marker(B, code) or {}).get("versions") or []) + [ver])
        freed = 0
        if delete_local:
            m["state"] = "deleting"; _write_marker(B, code, m)            # BEFORE the first delete: where the files are is never lost
            _set(code, "moving", "removing the verified Mac copies")
            for f in files:
                p = os.path.join(B, f["rel"])
                try: os.remove(p); freed += f["size"]
                except FileNotFoundError: pass
            for t in mv:                                         # empty folders of raw/<code>, subjects/<code>
                a = os.path.join(B, t)
                if os.path.isdir(a) and not os.path.islink(a):
                    for r, ds, fs in sorted(os.walk(a, topdown=False), key=lambda x: -len(x[0])):
                        try: os.rmdir(r)
                        except OSError: pass
            m["state"] = "in_pensieve"
        m["freed_bytes"] = freed
        _write_marker(B, code, m)
        _copy_marker_to_pensieve(B, vault, code, root)
        _set(code, m["state"], f"{len(files)} files ({freed / 1e6:.0f} MB) in Pensieve" if delete_local else "copied to Pensieve")
        return dict(ok=True, version=ver, moved_bytes=freed, kept_local=kept, files=len(files), state=m["state"])
    except Exception as e:
        _set(code, "failed", "", f"{type(e).__name__}: {e}")
        return dict(ok=False, error=STATUS[code]["error"])
    finally:
        LOCK.release()


def _copy_marker_to_pensieve(B, vault, code, root):
    """the version folder gets its own manifest (write-once, same journaled copy)"""
    try:
        from uengine.transfer.service import TransferService
        svc = TransferService(B, vault)
        try: svc.transfer("archive", [(marker_path(B, code), os.path.join(root, "pensieve_manifest.json"))], study_id=code)
        finally: svc.close()
    except Exception:
        pass                                                      # the Mac marker is the source of truth


def _restore_policy(B, vault, code):
    """PathPolicy that additionally allows writing THIS study's missing files under raw/<code>/ and data/<code>_*"""
    from uengine.safety import PathPolicy, canon, inside

    class RestorePolicy(PathPolicy):
        def protected_reason(self, c):
            why = super().protected_reason(c)
            if not why: return None
            raw_root = canon(os.path.join(B, "raw", code))
            in_raw = inside(c, raw_root) and c != raw_root
            in_data = os.path.dirname(c) == canon(os.path.join(B, "data")) and os.path.basename(c).startswith(f"{code}_")
            part = ".part-" in os.path.basename(c)
            if (in_raw or in_data) and (part or not os.path.lexists(c)): return None
            return why
    return RestorePolicy(B, vault)


def restore(B, vault, code):
    """bring the moved files back to the Mac (missing files only), verify each SHA-256 against the marker"""
    from uengine.safety import validate_study_code
    from uengine.transfer.service import TransferService
    validate_study_code(code)
    m = read_marker(B, code)
    if not m or m.get("state") not in AWAY: return dict(ok=True, noop=True, state=(m or {}).get("state", "on_mac"))
    if not LOCK.acquire(blocking=False): return dict(ok=False, error="another Pensieve move or restore is running")
    try:
        if not vault or not os.path.isdir(vault):
            _set(code, "failed", "", "connect the Pensieve drive to open this study")
            return dict(ok=False, error=STATUS[code]["error"], need_drive=True)
        root = os.path.join(vault, m["vault_rel"])
        todo = [f for f in m.get("files", []) if not os.path.exists(os.path.join(B, f["rel"]))]
        missing_src = [f["rel"] for f in todo if not os.path.isfile(os.path.join(root, f["rel"]))]
        if missing_src:
            _set(code, "failed", "", f"{len(missing_src)} file(s) missing on Pensieve (e.g. {missing_src[0]}) - nothing was changed")
            return dict(ok=False, error=STATUS[code]["error"])
        _set(code, "restoring", f"bringing {len(todo)} files back to the Mac")
        if todo:
            for f in todo: os.makedirs(os.path.dirname(os.path.join(B, f["rel"])), exist_ok=True)
            svc = TransferService(B, vault)
            svc.policy = _restore_policy(B, vault, code)
            try:
                rep = svc.transfer("restore", [(os.path.join(root, f["rel"]), os.path.join(B, f["rel"])) for f in todo], study_id=code)
            finally:
                svc.close()
            if not rep.get("ok"):
                err = "; ".join(rep.get("errors") or []) or rep.get("state") or "the copy did not complete"
                _set(code, "failed", "", f"restore failed: {err}")
                return dict(ok=False, error=STATUS[code]["error"], job_id=rep.get("job_id"))
        bad = [f["rel"] for f in m.get("files", []) if not os.path.isfile(os.path.join(B, f["rel"])) or _sha(os.path.join(B, f["rel"])) != f["sha256"]]
        if bad:
            _set(code, "failed", "", f"{len(bad)} restored file(s) do not match the record (e.g. {bad[0]}) - the Pensieve copy is unchanged")
            return dict(ok=False, error=STATUS[code]["error"])
        m.update(state="on_mac", restored_at=time.time()); _write_marker(B, code, m)
        _set(code, "on_mac", f"{len(todo)} files back on the Mac")
        return dict(ok=True, restored=len(todo))
    except Exception as e:
        _set(code, "failed", "", f"{type(e).__name__}: {e}")
        return dict(ok=False, error=STATUS[code]["error"])
    finally:
        LOCK.release()


def ensure_local(B, vault, code):
    """every feature that READS a study's images calls this first: brings a moved study back (verified) or says why not.
    -> dict(ok, restored=n) ; ok with restored=0 when the study is on the Mac"""
    if not in_pensieve(B, code): return dict(ok=True, restored=0)
    r = restore(B, vault, code)
    if r.get("ok"): return dict(ok=True, restored=r.get("restored", 0))
    return dict(ok=False, in_pensieve=True, error=f"{code} is in Pensieve and could not be brought back: {r.get('error')}")


def marker_file(B, code, rel):
    """the recorded {rel, size, sha256} of a moved file (None if not moved) - lets checks work without the file on the Mac"""
    m = read_marker(B, code) or {}
    if m.get("state") not in AWAY: return None
    return next((f for f in m.get("files", []) if f.get("rel") == rel), None)


def start_restore(B, vault, code):
    """restore in a background thread (reviewer / app); poll state(B, code) / STATUS"""
    if STATUS.get(code, {}).get("state") == "restoring": return dict(ok=True, running=True)
    _set(code, "restoring", "starting")
    threading.Thread(target=restore, args=(B, vault, code), daemon=True, name=f"pensieve-restore-{code}").start()
    return dict(ok=True, started=True)


def status(B, code):
    s = dict(STATUS.get(code) or {})
    m = read_marker(B, code) or {}
    if s.get("state") not in ("moving", "restoring", "failed"): s["state"] = m.get("state", "on_mac")
    s.update(version=m.get("version"), archived_at=m.get("archived_at"), restored_at=m.get("restored_at"),
             files=len(m.get("files", [])), freed_bytes=m.get("freed_bytes", 0))
    return s


def summary(B, codes):
    """per-state counts for the GUI"""
    out = {}
    for c in codes:
        st = state(B, c); out[st] = out.get(st, 0) + 1
    return out
