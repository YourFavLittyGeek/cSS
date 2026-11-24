#!/usr/bin/env python3
"""review_io.py - Phase 3A.1: crash-safe writes, cross-process study locks, append-only reviewer event journals, recovery.
Research software. Used by review_web.py (reviewer) and call_ledger.py (reviewer + app). No new packages (stdlib + pandas).

Writes
  atomic_write_bytes/text/json(path, ...)  unique temporary file in the same folder -> flush -> fsync -> os.replace -> fsync(folder):
                                           a crash leaves either the complete old file or the complete new file, never a torn one.
  append_line(path, line)                  O_APPEND + fsync; a torn last line of an earlier crash is closed first.
Locks
  study_lock(base, sid)                    fcntl.flock on review/.<sid>.lock (between processes: several reviewer windows, the app)
                                           + a per-process re-entrant lock (between threads; nested use in one thread is allowed).
Journals (provenance; append-only, never rewritten)
  review/<sid>_events_<reviewer>.jsonl     one fsynced JSON line per change made by that reviewer (calls, comments, audit calls,
                                           missed-cSS marks, final saves, consolidation, carry-over confirmations); each line holds
                                           the SHA-256 of the previous line (hash chain) and, for files, the SHA-256 of the file
                                           written. Written BEFORE the file it describes (write-ahead), so a crash between the two is
                                           repaired by rolling the file forward from the journal.
Recovery (ensure_table / ensure_missed, called under the study lock before every read-for-write and every write)
  file == journal head                     nothing to do
  file missing / equal to an EARLIER state the journal knows / truncated prefix of the head / unreadable
                                           -> unreadable or truncated copies go to review/quarantine/ (never deleted); the file is
                                              rebuilt byte-for-byte from the journal; a 'recovered' event records it
  file readable but unknown to the journal -> changed by another tool (older scripts, restore, a person): NOT overwritten; its full
                                              content is journaled as an 'external_change' baseline (provenance kept)
  file unreadable and no journal           -> RecoveryError: the reviewer is told; nothing starts empty and nothing is overwritten
"""
import contextlib, datetime, errno, fcntl, hashlib, io, json, os, re, shutil, tempfile, threading, time
import pandas as pd

try:                                                                     # test-only crash points (no-op unless PERCIVAL_TEST_ISOLATION=1)
    from uengine.transfer.crashpoints import crash as _crash
except Exception:                                                        # installed scripts without the engine: never crash on purpose
    def _crash(name): return None

SCHEMA = "review-events/1.0"
TMP_PREFIX = ".rio-"
LOCK_TIMEOUT_S = 60.0
_SID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
slug = lambda s: re.sub(r"[^A-Za-z0-9]+", "_", str(s).strip()).strip("_") or "reviewer"      # the same as review_web / call_ledger


class LockTimeout(OSError):
    pass


class RecoveryError(RuntimeError):
    pass


def _now(): return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
def sha256_bytes(b): return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    try:
        with open(p, "rb") as f: return sha256_bytes(f.read())
    except FileNotFoundError: return ""


# ------------------------------------------------------------------ crash-safe writes
def _fsync_dir(d):
    fd = os.open(d, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def atomic_write_bytes(path, data):
    d = os.path.dirname(os.path.abspath(path)); os.makedirs(d, exist_ok=True)
    try: mode = os.stat(path).st_mode & 0o7777
    except FileNotFoundError: mode = 0o644
    fd, tmp = tempfile.mkstemp(prefix=TMP_PREFIX + os.path.basename(path) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp, mode)
        _crash("review_io.after_tmp_write")
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    _crash("review_io.after_replace")
    _fsync_dir(d)


def atomic_write_text(path, text): atomic_write_bytes(path, text.encode("utf-8"))
def atomic_write_json(path, obj): atomic_write_text(path, json.dumps(obj, indent=1, default=str))


def atomic_copy(src, dst):
    with open(src, "rb") as f: atomic_write_bytes(dst, f.read())
    shutil.copystat(src, dst)


def append_line(path, line):
    """append one line (O_APPEND, fsync). If the file ends without a newline (a torn line of an earlier crash), it is closed first, so
    the new line is never glued to the torn one."""
    data = (line if line.endswith("\n") else line + "\n").encode("utf-8")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        size = os.fstat(fd).st_size
        if size:
            rfd = os.open(path, os.O_RDONLY)
            try: last = os.pread(rfd, 1, size - 1)
            finally: os.close(rfd)
            if last != b"\n": data = b"\n" + data
        view = memoryview(data)
        while view:
            n = os.write(fd, view); view = view[n:]
        os.fsync(fd)
    finally: os.close(fd)


def clean_orphan_tmp(folder, older_than_s=3600):
    """remove temporary files this module left behind after a crash (only its own prefix, only old ones)"""
    n = 0
    try: names = os.listdir(folder)
    except OSError: return 0
    for f in names:
        if f.startswith(TMP_PREFIX) and f.endswith(".tmp"):
            p = os.path.join(folder, f)
            try:
                if time.time() - os.path.getmtime(p) > older_than_s: os.unlink(p); n += 1
            except OSError: pass
    return n


# ------------------------------------------------------------------ locks
class _Lock:
    def __init__(self):
        self.rlock = threading.RLock(); self.fd = None; self.depth = 0


_LOCKS = {}
_GUARD = threading.Lock()


def check_sid(sid):
    if not isinstance(sid, str) or not _SID_OK.match(sid): raise ValueError(f"not a valid study key: {sid!r}")
    return sid


@contextlib.contextmanager
def named_lock(path, timeout=LOCK_TIMEOUT_S):
    path = os.path.abspath(path)
    with _GUARD: L = _LOCKS.setdefault(path, _Lock())
    if not L.rlock.acquire(timeout=timeout):
        raise LockTimeout(errno.EAGAIN, f"another save of this study is still running in this window - try again ({os.path.basename(path)})")
    try:
        if L.depth == 0:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644); deadline = time.monotonic() + timeout
            while True:
                try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        os.close(fd)
                        raise LockTimeout(errno.EAGAIN, f"another reviewer window or the app is saving this study - try again ({os.path.basename(path)})")
                    time.sleep(0.02)
            L.fd = fd
        L.depth += 1
        try: yield
        finally:
            L.depth -= 1
            if L.depth == 0:
                try: fcntl.flock(L.fd, fcntl.LOCK_UN)
                finally: os.close(L.fd); L.fd = None
    finally: L.rlock.release()


def study_lock(base, sid, timeout=LOCK_TIMEOUT_S):
    return named_lock(os.path.join(base, "review", f".{check_sid(sid)}.lock"), timeout)


def project_lock(base, name, timeout=LOCK_TIMEOUT_S):
    return named_lock(os.path.join(base, "review", f".{name}.lock"), timeout)


# ------------------------------------------------------------------ journals
def journal_path(base, sid, reviewer): return os.path.join(base, "review", f"{check_sid(sid)}_events_{slug(reviewer)}.jsonl")


def _line_bytes(ev): return json.dumps(ev, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def read_journal(path):
    """-> (events [dict, oldest first], problems [str]). Unreadable lines (torn by a crash, damaged) are skipped and reported; the hash
    chain and the sequence numbers are verified (a break is reported, the events are still returned)."""
    ev, probs = [], []
    try:
        with open(path, "rb") as f: raw = f.read()
    except FileNotFoundError: return [], []
    prev_hash, prev_seq = "", 0
    lines = raw.split(b"\n")
    for i, ln in enumerate(lines, 1):
        if not ln.strip(): continue
        try: e = json.loads(ln)
        except Exception:
            probs.append(f"line {i}: unreadable ({'torn last line' if i >= len(lines) - 1 else 'damaged'}) - skipped"); continue
        if not isinstance(e, dict) or e.get("schema") != SCHEMA:
            probs.append(f"line {i}: not a review event - skipped"); continue
        if e.get("prev", "") != prev_hash: probs.append(f"line {i}: hash chain broken (seq {e.get('seq')})")
        if e.get("seq") != prev_seq + 1: probs.append(f"line {i}: sequence {e.get('seq')} after {prev_seq}")
        prev_hash, prev_seq = sha256_bytes(_line_bytes(e)), int(e.get("seq") or prev_seq)
        if _line_bytes(e) != ln: probs.append(f"line {i}: not in canonical form")
        ev.append(e)
    return ev, probs


def journal_append(base, sid, reviewer, kind, **fields):
    """append one event to the reviewer's journal (caller holds the study lock) -> the event"""
    p = journal_path(base, sid, reviewer); ev, _ = read_journal(p)
    last = ev[-1] if ev else None
    e = dict(schema=SCHEMA, seq=(int(last["seq"]) + 1) if last else 1, prev=sha256_bytes(_line_bytes(last)) if last else "",
             time=_now(), study=sid, reviewer=str(reviewer).strip(), kind=kind, **fields)
    append_line(p, _line_bytes(e).decode("utf-8"))
    _crash("review_io.after_journal")
    return e


def study_events(base, sid):
    """every reviewer's events of one study -> [(journal file, event)] in time order"""
    out = []
    pre = os.path.join(base, "review", f"{check_sid(sid)}_events_")
    for p in sorted(os.listdir(os.path.join(base, "review"))) if os.path.isdir(os.path.join(base, "review")) else []:
        fp = os.path.join(base, "review", p)
        if fp.startswith(pre) and fp.endswith(".jsonl"):
            ev, _ = read_journal(fp); out += [(fp, e) for e in ev]
    return sorted(out, key=lambda t: (t[1].get("time", ""), t[1].get("seq", 0)))


# ------------------------------------------------------------------ CSV tables (per-reviewer calls, excluded-object audit calls)
def split_records(text):
    """CSV text -> (header line, [record lines]) - quote-aware, so a comment with a newline stays one record"""
    recs, cur, q = [], [], False
    for ch in text:
        if ch == '"': q = not q
        if ch == "\n" and not q:
            recs.append("".join(cur)); cur = []
        else: cur.append(ch)
    if cur: recs.append("".join(cur))
    return (recs[0] if recs else ""), recs[1:]


def _render(header, order, lines): return "\n".join([header] + [lines[k] for k in order]) + "\n"


def _table_events(base, sid, reviewer, table):
    ev, probs = read_journal(journal_path(base, sid, reviewer))
    return [e for e in ev if e.get("table") == table], probs


def table_states(events):
    """replay -> [(event, text after it)]"""
    out, header, order, lines = [], "", [], {}
    for e in events:
        if "snapshot" in e:
            header, recs = split_records(e["snapshot"]); order = [f"#{i}" for i in range(len(recs))]; lines = dict(zip(order, recs))
        else:
            if e.get("header") is not None: header = e["header"]
            for k in e.get("removed", []): lines.pop(k, None)
            for k, ln in e.get("upserts", {}).items(): lines[k] = ln
            if e.get("order") is not None: order = list(e["order"])
            else: order = [k for k in order if k in lines] + [k for k in e.get("upserts", {}) if k not in order]
        txt = _render(header, order, lines) if header else ""
        out.append((e, txt, header, list(order), dict(lines)))
    return out


def _readable(text, need):
    try:
        d = pd.read_csv(io.StringIO(text))
        return all(c in d.columns for c in need)
    except Exception: return False


def _quarantine(base, path, why):
    qd = os.path.join(base, "review", "quarantine"); os.makedirs(qd, exist_ok=True)
    dst = os.path.join(qd, f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{why}_{os.path.basename(path)}")
    atomic_copy(path, dst); return os.path.relpath(dst, base)


def ensure_table(base, sid, reviewer, table, path, need=("call",)):
    """make the reviewer's file consistent with the journal BEFORE it is read for a change (caller holds the study lock).
    -> dict(status, detail). Raises RecoveryError when the file is unreadable and no journal can rebuild it."""
    rel = os.path.relpath(path, base)
    ev, probs = _table_events(base, sid, reviewer, table)
    exists = os.path.exists(path)
    cur = open(path, "rb").read() if exists else b""
    cur_txt = cur.decode("utf-8", "replace")
    if not ev:
        if exists and not _readable(cur_txt, need):
            raise RecoveryError(f"{rel} cannot be read and no event journal exists to rebuild it - it was left unchanged; "
                                f"restore it from a backup (nothing was overwritten)")
        return dict(status="no_journal", detail="")
    states = table_states(ev); head_txt = states[-1][1]; head_sha = sha256_bytes(head_txt.encode())
    if exists and sha256_bytes(cur) == head_sha: return dict(status="ok", detail="")
    # roll forward ONLY from the state just before the head (= a crash between the journal line and the file); an older state is a
    # deliberate restore by someone and is kept (recorded below as an external change)
    before = sha256_bytes(states[-2][1].encode()) if len(states) > 1 else sha256_bytes(b"")
    if not exists: why = "missing"
    elif sha256_bytes(cur) == before and states[-1][0].get("kind") not in ("baseline", "external_change"): why = "behind_journal"
    elif not _readable(cur_txt, need): why = "unreadable"
    elif sha256_bytes(cur) in {sha256_bytes(x[1].encode()) for x in states[:-1]}: why = ""          # an earlier state = deliberate restore
    elif head_txt.startswith(cur_txt) and len(cur_txt) < len(head_txt): why = "truncated"
    else: why = ""
    if not why:
        journal_append(base, sid, reviewer, "external_change", table=table, file=rel, snapshot=cur_txt, file_sha256=sha256_bytes(cur),
                       note="file changed outside the reviewer (another tool, a restore or a person); kept as found")
        return dict(status="external_change", detail=f"{rel}: changed outside the reviewer - kept and recorded")
    q = _quarantine(base, path, why) if exists and why in ("unreadable", "truncated") else ""
    journal_append(base, sid, reviewer, "recovered", table=table, file=rel, reason=why, quarantined=q, file_sha256=head_sha,
                   journal_problems=probs[:20])
    atomic_write_text(path, head_txt)
    return dict(status="recovered", detail=f"{rel}: {why} - rebuilt from the event journal" + (f" (damaged copy kept in {q})" if q else ""))


def write_table(base, sid, reviewer, table, path, df, key_cols, kind, **info):
    """write a reviewer's CSV table (exact pandas to_csv text, unchanged format) with a write-ahead journal event holding the changed
    records. The caller holds the study lock and has called ensure_table. -> the event (None when nothing changed)"""
    rel = os.path.relpath(path, base)
    _crash("review_io.table_write")                                      # test hook (delay / crash) - inside the caller's study lock
    text = df.to_csv(index=False)
    header, recs = split_records(text)
    keys = ["|".join(str(r[c]) for c in key_cols) for _, r in df.iterrows()]
    ev, _ = _table_events(base, sid, reviewer, table)
    old = sha256_file(path)
    if ev and old == sha256_bytes(text.encode()): return None
    if len(recs) != len(keys) or len(set(keys)) != len(keys):            # cannot key the records safely: store the whole file
        e = journal_append(base, sid, reviewer, kind, table=table, file=rel, snapshot=text, file_sha256=sha256_bytes(text.encode()), **info)
    else:
        if not ev and os.path.exists(path):                                # first journaled change of an existing file: its content first
            prev = open(path, "rb").read()
            journal_append(base, sid, reviewer, "baseline", table=table, file=rel, snapshot=prev.decode("utf-8", "replace"),
                           file_sha256=sha256_bytes(prev), note="content found before journaling started")
            ev, _ = _table_events(base, sid, reviewer, table)
        st = table_states(ev)[-1] if ev else (None, "", "", [], {})
        _, _, oh, oorder, olines = st
        new_lines = dict(zip(keys, recs))
        # snapshot-keyed (#i) states are re-keyed by content on the next write: compare by record text
        if any(k.startswith("#") for k in oorder):
            removed = list(oorder); upserts = new_lines; order = keys
        else:
            removed = [k for k in oorder if k not in new_lines]
            upserts = {k: v for k, v in new_lines.items() if olines.get(k) != v}
            implied = [k for k in oorder if k in new_lines] + [k for k in keys if k not in oorder]
            order = None if implied == keys else keys
        e = journal_append(base, sid, reviewer, kind, table=table, file=rel, header=header if header != oh else None, removed=removed,
                           upserts=upserts, order=order, file_sha256=sha256_bytes(text.encode()), **info)
    atomic_write_text(path, text)
    _crash("review_io.after_table_write")
    return e


def write_table_text(base, sid, reviewer, table, path, text, kind, **info):
    """write a reviewer table from exact text (e.g. a restored archive copy): a snapshot event, then the file"""
    e = journal_append(base, sid, reviewer, kind, table=table, file=os.path.relpath(path, base), snapshot=text,
                       file_sha256=sha256_bytes(text.encode()), **info)
    atomic_write_text(path, text)
    return e


# ------------------------------------------------------------------ the shared missed-cSS file (all reviewers; full snapshots, small)
def _missed_events(base, sid): return [(p, e) for p, e in study_events(base, sid) if e.get("table") == "missed"]


def ensure_missed(base, sid, path, by=""):
    """the shared ID_missed.csv against every reviewer's journal (newest snapshot wins). Same outcomes as ensure_table."""
    rel = os.path.relpath(path, base); ev = _missed_events(base, sid)
    exists = os.path.exists(path); cur = open(path, "rb").read() if exists else b""; cur_txt = cur.decode("utf-8", "replace")
    if not ev:
        if exists and not _readable(cur_txt, ("missed_id",)):
            raise RecoveryError(f"{rel} cannot be read and no event journal exists to rebuild it - it was left unchanged; restore it from a backup")
        return dict(status="no_journal", detail="")
    head = ev[-1][1]["snapshot"]; head_sha = sha256_bytes(head.encode())
    if exists and sha256_bytes(cur) == head_sha: return dict(status="ok", detail="")
    before = sha256_bytes(ev[-2][1]["snapshot"].encode()) if len(ev) > 1 else sha256_bytes(b"")
    if not exists: why = "missing"
    elif sha256_bytes(cur) == before and ev[-1][1].get("kind") not in ("baseline", "external_change"): why = "behind_journal"
    elif not _readable(cur_txt, ("missed_id",)): why = "unreadable"
    elif sha256_bytes(cur) in {sha256_bytes(e["snapshot"].encode()) for _, e in ev[:-1]}: why = ""
    elif head.startswith(cur_txt) and len(cur_txt) < len(head): why = "truncated"
    else: why = ""
    if not why:
        journal_append(base, sid, by or "(unknown)", "external_change", table="missed", file=rel, snapshot=cur_txt, file_sha256=sha256_bytes(cur),
                       note="file changed outside the reviewer; kept as found")
        return dict(status="external_change", detail=f"{rel}: changed outside the reviewer - kept and recorded")
    q = _quarantine(base, path, why) if exists and why in ("unreadable", "truncated") else ""
    journal_append(base, sid, by or "(recovery)", "recovered", table="missed", file=rel, reason=why, quarantined=q, snapshot=head, file_sha256=head_sha)
    atomic_write_text(path, head)
    return dict(status="recovered", detail=f"{rel}: {why} - rebuilt from the event journals" + (f" (damaged copy kept in {q})" if q else ""))


def write_missed(base, sid, reviewer, path, df, kind, **info):
    rel = os.path.relpath(path, base); text = df.to_csv(index=False)
    _crash("review_io.table_write")
    if not _missed_events(base, sid) and os.path.exists(path):
        prev = open(path, "rb").read()
        journal_append(base, sid, reviewer, "baseline", table="missed", file=rel, snapshot=prev.decode("utf-8", "replace"),
                       file_sha256=sha256_bytes(prev), note="content found before journaling started")
    e = journal_append(base, sid, reviewer, kind, table="missed", file=rel, snapshot=text, file_sha256=sha256_bytes(text.encode()), **info)
    atomic_write_text(path, text)
    _crash("review_io.after_table_write")
    return e


def verify_study(base, sid):
    """read-only integrity report of one study: every journal's chain + whether each journaled file equals its journal head"""
    rep = dict(study=sid, journals=[], files=[])
    rd = os.path.join(base, "review")
    for f in sorted(os.listdir(rd)) if os.path.isdir(rd) else []:
        if f.startswith(f"{sid}_events_") and f.endswith(".jsonl"):
            ev, probs = read_journal(os.path.join(rd, f)); rep["journals"].append(dict(file=f, events=len(ev), problems=probs))
            for table in sorted({e.get("table") for e in ev if e.get("table") and e.get("table") != "missed"}):
                te = [e for e in ev if e.get("table") == table]; st = table_states(te); fp = os.path.join(base, te[-1]["file"])
                rep["files"].append(dict(file=te[-1]["file"], matches_journal=sha256_file(fp) == sha256_bytes(st[-1][1].encode())))
    me = _missed_events(base, sid)
    if me:
        fp = os.path.join(base, me[-1][1]["file"])
        rep["files"].append(dict(file=me[-1][1]["file"], matches_journal=sha256_file(fp) == sha256_bytes(me[-1][1]["snapshot"].encode())))
    rep["ok"] = all(not j["problems"] for j in rep["journals"]) and all(f["matches_journal"] for f in rep["files"])
    return rep
