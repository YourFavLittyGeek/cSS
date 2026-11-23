"""uengine/storage/activity.py - Phase 1e: real filesystem activity on a volume (read only).

journal_activity(project, mount)  the durable transfer journal, opened READ-ONLY (sqlite mode=ro; never created):
                                  jobs in an active state with any source / destination / staged / published path on
                                  the volume ("active"), and paused / interrupted / needs-attention jobs that will need
                                  the volume to be resumed or discarded ("parked").
open_handles(mount)               every process holding a file open on that filesystem (/usr/sbin/lsof, read only).
                                  None = could not be determined (callers must treat that as NOT safe).
"""
import os
import sqlite3
import subprocess
import sys
from typing import Any, Dict, List, Optional

ACTIVE = ("preparing", "copying", "flushing", "verifying", "committing", "removing_sources", "rolling_back", "recovering",
          "cancel_requested")
PARKED = ("paused", "interrupted", "needs_attention")
LSOF = "/usr/sbin/lsof"


def _k(p: str) -> str:
    return p.lower() if sys.platform == "darwin" else p


def on_volume(path: Optional[str], mount: str) -> bool:
    if not path:
        return False
    p, m = _k(os.path.realpath(path)), _k(os.path.realpath(mount)).rstrip("/")
    return p == m or p.startswith(m + "/")


def journal_activity(project_base: str, mount: str) -> Dict[str, List[Dict[str, Any]]]:
    out = {"active": [], "parked": [], "journal": "absent"}
    db = os.path.join(project_base, "app_data", "transfers", "journal.db")
    if not os.path.exists(db):
        return out
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            jobs = con.execute(f"SELECT job_id, state, operation FROM jobs WHERE state IN ({','.join('?' * (len(ACTIVE) + len(PARKED)))})",
                               (*ACTIVE, *PARKED)).fetchall()
            for j in jobs:
                files = con.execute("SELECT src, dst, part_path, committed_path, preserved_path FROM job_files WHERE job_id=?",
                                    (j["job_id"],)).fetchall()
                hits = sum(1 for f in files if any(on_volume(f[c], mount) for c in f.keys()))
                if hits:
                    rec = dict(job_id=j["job_id"], state=j["state"], operation=j["operation"], files_on_volume=hits)
                    out["active" if j["state"] in ACTIVE else "parked"].append(rec)
        finally:
            con.close()
        out["journal"] = "read"
    except sqlite3.Error as e:
        out["journal"] = f"unreadable: {e}"
    return out


def open_handles(mount: str, runner=None, timeout: float = 15.0) -> Optional[List[Dict[str, Any]]]:
    """processes with open files on the filesystem mounted at `mount` (lsof +f -- mount). None if unknown."""
    cmd = [LSOF, "-w", "-F", "pcn", "+f", "--", mount]
    try:
        r = runner(cmd) if runner else subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode not in (0, 1) or (r.returncode == 1 and (r.stderr or "").strip()):
        return None                                  # lsof failed: activity cannot be ruled out
    procs: Dict[str, Dict[str, Any]] = {}
    cur = None
    for line in (r.stdout or "").splitlines():
        if not line:
            continue
        tag, val = line[0], line[1:]
        if tag == "p":
            cur = procs.setdefault(val, dict(pid=int(val), command="", files=[]))
        elif cur is not None and tag == "c":
            cur["command"] = val
        elif cur is not None and tag == "n" and len(cur["files"]) < 10:
            cur["files"].append(val)
    return list(procs.values())                     # Percival's own open files count too
