"""uengine/transfer/guards.py - Phase 1e.2: block migrations and conflicting maintenance while transfers are unfinished.

Read-only view of the durable journal (sqlite mode=ro; never created). "Unfinished" = any job that is queued, active,
paused, interrupted or needs attention: its files (sources, destinations, staged .part files, published files, moved-
aside previous versions) may be needed by a later resume / discard and must not be removed, moved or cleaned up.

  MIGRATIONS_DISABLED                working-directory and legacy-data migrations are refused outright until a
                                     separately approved migration workflow exists (plan / discover stay available)
  unfinished_jobs(base)              all unfinished jobs
  conflicts_with_paths(base, paths)  unfinished jobs with a file inside / equal to one of `paths`
  conflicts_with_study(base, code)   unfinished jobs of that study, or touching its work / staging / subjects folders
"""
import os
import sqlite3
from typing import Any, Dict, Iterable, List

from ..storage.activity import on_volume

UNFINISHED = ("queued", "preparing", "copying", "flushing", "verifying", "committing", "removing_sources", "rolling_back",
              "recovering", "cancel_requested", "paused", "interrupted", "needs_attention")
MIGRATIONS_DISABLED = ("Refused: data migrations are disabled until a separately approved migration workflow exists "
                       "(planning and discovery remain available; nothing was copied, moved or reconfigured)")


def _rows(base: str):
    db = os.path.join(base, "app_data", "transfers", "journal.db")
    if not os.path.exists(db):
        return [], {}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        jobs = [dict(r) for r in con.execute(
            f"SELECT job_id, state, operation, study_id FROM jobs WHERE state IN ({','.join('?' * len(UNFINISHED))})", UNFINISHED)]
        files = {j["job_id"]: [dict(f) for f in con.execute(
            "SELECT src, dst, part_path, committed_path, preserved_path FROM job_files WHERE job_id=?", (j["job_id"],))]
            for j in jobs}
    finally:
        con.close()
    return jobs, files


def unfinished_jobs(base: str) -> List[Dict[str, Any]]:
    return _rows(base)[0]


def conflicts_with_paths(base: str, paths: Iterable[str]) -> List[Dict[str, Any]]:
    paths = [p for p in paths if p]
    jobs, files = _rows(base)
    out = []
    for j in jobs:
        if any(on_volume(f[c], p) for f in files[j["job_id"]] for c in f for p in paths):
            out.append(j)
    return out


def conflicts_with_study(base: str, code: str) -> List[Dict[str, Any]]:
    if not code:
        return []
    folders = [os.path.join(base, "work", code), os.path.join(base, "app_data", "staging", code), os.path.join(base, "subjects", code)]
    hits = {j["job_id"]: j for j in conflicts_with_paths(base, folders)}
    for j in unfinished_jobs(base):
        if j.get("study_id") == code:
            hits[j["job_id"]] = j
    return list(hits.values())


def refusal(jobs: List[Dict[str, Any]], what: str) -> Dict[str, Any]:
    ids = ", ".join(f"{j['job_id']} ({j['state']})" for j in jobs[:5])
    return dict(ok=False, error=f"Refused: {what} would conflict with {len(jobs)} unfinished transfer job(s): {ids}. "
                                f"Finish, resume or discard them first.",
                blocked_by=[dict(job_id=j["job_id"], state=j["state"]) for j in jobs])
