"""uengine/transfer/journal.py - Phase 1a: the persistent transfer journal (single source of truth for jobs).

SQLite at <project>/app_data/transfers/journal.db, WAL, synchronous=FULL, foreign keys on. Every state change is ONE
transaction that (1) checks the current state, (2) checks the transition against models.py, (3) writes the new state and
(4) appends a job_events row - so the stored state and its history can never disagree, and an illegal or stale
transition changes nothing. Progress counters are updated without a state change.

The journal only records; it never touches transfer data. It is written by the transfer service (milestone 1b).
"""
import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .models import (FileState, JobState, NON_TERMINAL_JOB_STATES, TransitionError, check_file_transition,
                     check_job_transition)
from ..safety import PathPolicy, SafetyError, is_simple_name

SCHEMA_VERSION = 3          # v2 (1c): identities, intents, recovery decision, created folders; v3 (1d): control request
JOURNAL_RELPATH = os.path.join("app_data", "transfers", "journal.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    study_id TEXT,
    commit_mode TEXT NOT NULL,
    state TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    total_files INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    done_files INTEGER NOT NULL DEFAULT 0,
    done_bytes INTEGER NOT NULL DEFAULT 0,
    phase_bytes INTEGER NOT NULL DEFAULT 0,
    current_file TEXT,
    error TEXT,
    owner_pid INTEGER,
    heartbeat REAL,
    recovery_decision TEXT,
    recovery_attempts INTEGER NOT NULL DEFAULT 0,
    created_dirs TEXT NOT NULL DEFAULT '[]',
    control TEXT,
    request_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS job_files (
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    seq INTEGER NOT NULL,
    rel_path TEXT NOT NULL,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    size INTEGER NOT NULL,
    state TEXT NOT NULL,
    src_mtime_ns INTEGER,
    src_ino INTEGER,
    src_sha256 TEXT,
    part_path TEXT,
    part_sha256 TEXT,
    dst_sha256 TEXT,
    committed_path TEXT,
    preserved_path TEXT,
    error TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    src_identity TEXT,
    part_identity TEXT,
    old_identity TEXT,
    dst_identity TEXT,
    preserved_state TEXT NOT NULL DEFAULT 'none',
    intent TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (job_id, seq)
);
CREATE TABLE IF NOT EXISTS job_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    seq INTEGER,
    from_state TEXT,
    to_state TEXT,
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS ix_files_state ON job_files(job_id, state);
CREATE INDEX IF NOT EXISTS ix_events_job ON job_events(job_id, event_id);
"""

_FILE_FIELDS = {"src_mtime_ns", "src_ino", "src_sha256", "part_path", "part_sha256", "dst_sha256", "committed_path",
                "preserved_path", "error", "attempt", "src_identity", "part_identity", "old_identity", "dst_identity",
                "preserved_state", "intent"}
_JOB_FIELDS = {"recovery_decision", "recovery_attempts", "error", "control"}
# columns added by schema v2 (1c) - added to a v1 journal in place (ALTER TABLE ADD COLUMN; nothing is rewritten)
_V2_COLUMNS = {
    "jobs": [("recovery_decision", "TEXT"), ("recovery_attempts", "INTEGER NOT NULL DEFAULT 0"),
             ("created_dirs", "TEXT NOT NULL DEFAULT '[]'"), ("control", "TEXT"), ("request_id", "TEXT")],
    "job_files": [("attempt", "INTEGER NOT NULL DEFAULT 0"), ("src_identity", "TEXT"), ("part_identity", "TEXT"),
                  ("old_identity", "TEXT"), ("dst_identity", "TEXT"), ("preserved_state", "TEXT NOT NULL DEFAULT 'none'"),
                  ("intent", "TEXT")],
}


class JournalError(RuntimeError):
    pass


class DuplicateRequest(JournalError):
    """1d: a job with this request id already exists (idempotent creation)"""

    def __init__(self, request_id, job_id):
        super().__init__(f"request {request_id} already created job {job_id}")
        self.request_id, self.job_id = request_id, job_id


class StaleStateError(TransitionError):
    """the caller expected a different current state (another worker / request changed it first)"""


class TransferJournal:
    def __init__(self, project_base: str, vault_root: Optional[str] = None):
        if not project_base or not os.path.isdir(project_base):
            raise JournalError(f"project folder does not exist: {project_base!r}")
        self.path = os.path.join(os.path.abspath(project_base), JOURNAL_RELPATH)
        PathPolicy(project_base, vault_root).check_write_target(self.path)     # Phase 0 policy: never in a protected place
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=30000")
        with self._lock:
            self._conn.executescript(_SCHEMA)          # idempotent (IF NOT EXISTS); executescript manages its own commit
        self._check_schema()

    # ------------------------------------------------------------------ plumbing
    class _Tx:
        def __init__(self, j):
            self.j = j

        def __enter__(self):
            self.j._lock.acquire()
            self.j._conn.execute("BEGIN IMMEDIATE")
            return self.j._conn

        def __exit__(self, et, ev, tb):
            try:
                self.j._conn.execute("ROLLBACK" if et else "COMMIT")
            finally:
                self.j._lock.release()
            return False

    def _tx(self):
        return TransferJournal._Tx(self)

    def _check_schema(self) -> None:
        with self._tx() as c:
            row = c.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
            if row is None:
                c.execute("INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_jobs_request ON jobs(request_id) WHERE request_id IS NOT NULL")
                return
            v = int(row["value"])
            if v > SCHEMA_VERSION:
                raise JournalError(f"journal schema {row['value']} is newer than this program ({SCHEMA_VERSION}); refusing to use it")
            if v < SCHEMA_VERSION:                      # additive migration (v1/v2 -> v3) inside one transaction
                for table, cols in _V2_COLUMNS.items():
                    have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
                    for name, decl in cols:
                        if name not in have:
                            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                c.execute("UPDATE schema_meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
                c.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('migrated_from', ?)", (str(v),))
            # created only after the column exists (also for journals migrated from v1 / v2)
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_jobs_request ON jobs(request_id) WHERE request_id IS NOT NULL")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _event(c, job_id, kind, seq=None, frm=None, to=None, detail=None):
        c.execute("INSERT INTO job_events(job_id, ts, kind, seq, from_state, to_state, detail_json) VALUES (?,?,?,?,?,?,?)",
                  (job_id, time.time(), kind, seq, frm, to, json.dumps(detail, default=str) if detail is not None else None))

    # ------------------------------------------------------------------ jobs
    def create_job(self, job_id: str, operation: str, commit_mode: str, files: Sequence[Dict[str, Any]],
                   study_id: Optional[str] = None, spec: Optional[Dict[str, Any]] = None,
                   request_id: Optional[str] = None) -> None:
        """a new job in state QUEUED with its complete file list (atomic: all or nothing). request_id (optional,
        unique): a second creation with the same id raises DuplicateRequest naming the existing job."""
        if not is_simple_name(job_id) or len(job_id) > 128:
            raise JournalError(f"invalid job id {job_id!r}")
        if request_id is not None and (not is_simple_name(request_id) or len(request_id) > 64):
            raise JournalError(f"invalid request id {request_id!r}")
        now = time.time()
        with self._tx() as c:
            if c.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone():
                raise JournalError(f"job {job_id} already exists")
            if request_id is not None:
                row = c.execute("SELECT job_id FROM jobs WHERE request_id=?", (request_id,)).fetchone()
                if row:
                    raise DuplicateRequest(request_id, row["job_id"])
            total = sum(int(f["size"]) for f in files)
            c.execute("INSERT INTO jobs(job_id, operation, study_id, commit_mode, state, spec_json, total_files, total_bytes, "
                      "request_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (job_id, operation, study_id, commit_mode, JobState.QUEUED.value, json.dumps(spec or {}, default=str),
                       len(files), total, request_id, now, now))
            for i, f in enumerate(files):
                c.execute("INSERT INTO job_files(job_id, seq, rel_path, src, dst, size, state, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                          (job_id, i, f["rel_path"], f["src"], f["dst"], int(f["size"]), FileState.PENDING.value, now))
            self._event(c, job_id, "created", to=JobState.QUEUED.value, detail={"files": len(files), "bytes": total})

    def transition_job(self, job_id: str, new_state, expected: Optional[Iterable] = None, error: Optional[str] = None,
                       detail: Optional[Dict[str, Any]] = None, owner_pid: Optional[int] = None) -> str:
        """move a job to new_state (validated). expected: the state(s) the caller believes the job is in -> else
        StaleStateError and nothing changes. Returns the previous state."""
        new = JobState(new_state).value
        with self._tx() as c:
            row = c.execute("SELECT state FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise JournalError(f"unknown job {job_id}")
            cur = row["state"]
            if expected is not None and cur not in {JobState(e).value for e in expected}:
                raise StaleStateError(f"job {job_id} is {cur}, not {sorted(JobState(e).value for e in expected)}")
            check_job_transition(cur, new)
            sets, vals = ["state=?", "updated_at=?"], [new, time.time()]
            if error is not None:
                sets.append("error=?"); vals.append(error)
            if owner_pid is not None:
                sets += ["owner_pid=?", "heartbeat=?"]; vals += [owner_pid, time.time()]
            c.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id=?", (*vals, job_id))
            self._event(c, job_id, "state", frm=cur, to=new, detail=dict(detail or {}, **({"error": error} if error else {})))
            return cur

    def update_progress(self, job_id: str, done_files: Optional[int] = None, done_bytes: Optional[int] = None,
                        phase_bytes: Optional[int] = None, current_file: Optional[str] = None, heartbeat: bool = True) -> None:
        """progress counters only (no state change); refused for a job in a terminal state"""
        with self._tx() as c:
            row = c.execute("SELECT state, total_files, total_bytes FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise JournalError(f"unknown job {job_id}")
            if JobState(row["state"]) not in NON_TERMINAL_JOB_STATES:
                raise TransitionError(f"job {job_id} is {row['state']}: progress cannot change")
            sets, vals = ["updated_at=?"], [time.time()]
            for col, v, cap in (("done_files", done_files, row["total_files"]), ("done_bytes", done_bytes, row["total_bytes"]),
                                ("phase_bytes", phase_bytes, None)):
                if v is not None:
                    if v < 0 or (cap is not None and v > cap):
                        raise JournalError(f"{col}={v} outside 0..{cap}")
                    sets.append(f"{col}=?"); vals.append(int(v))
            if current_file is not None:
                sets.append("current_file=?"); vals.append(current_file)
            if heartbeat:
                sets.append("heartbeat=?"); vals.append(time.time())
            c.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id=?", (*vals, job_id))

    # ------------------------------------------------------------------ files
    def transition_file(self, job_id: str, seq: int, new_state, expected: Optional[Iterable] = None, **fields) -> str:
        bad = set(fields) - _FILE_FIELDS
        if bad:
            raise JournalError(f"unknown file fields {sorted(bad)}")
        new = FileState(new_state).value
        with self._tx() as c:
            row = c.execute("SELECT state FROM job_files WHERE job_id=? AND seq=?", (job_id, seq)).fetchone()
            if row is None:
                raise JournalError(f"unknown file {job_id}#{seq}")
            cur = row["state"]
            if expected is not None and cur not in {FileState(e).value for e in expected}:
                raise StaleStateError(f"file {job_id}#{seq} is {cur}")
            check_file_transition(cur, new)
            cols = ["state=?", "updated_at=?"] + [f"{k}=?" for k in fields]
            c.execute(f"UPDATE job_files SET {', '.join(cols)} WHERE job_id=? AND seq=?",
                      (new, time.time(), *fields.values(), job_id, seq))
            self._event(c, job_id, "file", seq=seq, frm=cur, to=new,
                        detail={k: v for k, v in fields.items() if k in ("error", "src_sha256", "dst_sha256", "preserved_path")} or None)
            return cur

    def update_file(self, job_id: str, seq: int, **fields) -> None:
        """write-ahead fields of a file WITHOUT a state change (e.g. part identity right after creation, intents)"""
        bad = set(fields) - _FILE_FIELDS
        if bad or not fields:
            raise JournalError(f"unknown / missing file fields {sorted(bad)}")
        with self._tx() as c:
            if c.execute("SELECT 1 FROM job_files WHERE job_id=? AND seq=?", (job_id, seq)).fetchone() is None:
                raise JournalError(f"unknown file {job_id}#{seq}")
            cols = [f"{k}=?" for k in fields] + ["updated_at=?"]
            c.execute(f"UPDATE job_files SET {', '.join(cols)} WHERE job_id=? AND seq=?", (*fields.values(), time.time(), job_id, seq))
            if {"intent", "preserved_state"} & set(fields):
                self._event(c, job_id, "intent", seq=seq, detail={k: fields[k] for k in ("intent", "preserved_state") if k in fields})

    def set_job(self, job_id: str, **fields) -> None:
        bad = set(fields) - _JOB_FIELDS
        if bad or not fields:
            raise JournalError(f"unknown / missing job fields {sorted(bad)}")
        with self._tx() as c:
            cols = [f"{k}=?" for k in fields] + ["updated_at=?"]
            if c.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE job_id=?", (*fields.values(), time.time(), job_id)).rowcount != 1:
                raise JournalError(f"unknown job {job_id}")
            self._event(c, job_id, "job_fields", detail=fields)

    def request_control(self, job_id: str, value: Optional[str]) -> None:
        """1d: a cooperative request ('pause') read by the job's owner at its next safe checkpoint (any process)"""
        if value not in (None, "pause"):
            raise JournalError(f"unknown control request {value!r}")
        self.set_job(job_id, control=value)

    def get_control(self, job_id: str) -> Optional[str]:
        with self._lock:
            r = self._conn.execute("SELECT control FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return r["control"] if r else None

    def add_created_dir(self, job_id: str, path: str) -> None:
        """write-ahead: record a folder BEFORE it is created, so recovery can remove it again (only if empty)"""
        with self._tx() as c:
            row = c.execute("SELECT created_dirs FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise JournalError(f"unknown job {job_id}")
            dirs = json.loads(row["created_dirs"] or "[]")
            if path not in dirs:
                dirs.append(path)
                c.execute("UPDATE jobs SET created_dirs=?, updated_at=? WHERE job_id=?", (json.dumps(dirs), time.time(), job_id))

    # ------------------------------------------------------------------ reads
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            r = self._conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return dict(r) if r else None

    def list_jobs(self, states: Optional[Iterable] = None, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            if states is None:
                rows = self._conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            else:
                st = [JobState(s).value for s in states]
                rows = self._conn.execute(f"SELECT * FROM jobs WHERE state IN ({','.join('?' * len(st))}) ORDER BY created_at DESC LIMIT ?",
                                          (*st, limit)).fetchall()
            return [dict(r) for r in rows]

    def non_terminal_jobs(self) -> List[Dict[str, Any]]:
        return self.list_jobs(NON_TERMINAL_JOB_STATES, limit=100000)

    def get_files(self, job_id: str, states: Optional[Iterable] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if states is None:
                rows = self._conn.execute("SELECT * FROM job_files WHERE job_id=? ORDER BY seq", (job_id,)).fetchall()
            else:
                st = [FileState(s).value for s in states]
                rows = self._conn.execute(f"SELECT * FROM job_files WHERE job_id=? AND state IN ({','.join('?' * len(st))}) ORDER BY seq",
                                          (job_id, *st)).fetchall()
            return [dict(r) for r in rows]

    def events(self, job_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute("SELECT * FROM job_events WHERE job_id=? ORDER BY event_id", (job_id,)).fetchall()]

    def pragma(self, name: str):
        with self._lock:
            return self._conn.execute(f"PRAGMA {name}").fetchone()[0]
