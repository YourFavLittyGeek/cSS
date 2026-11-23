"""uengine/transfer/api.py - Phase 1d: Transfer Center endpoints (backend only; the GUI is Phase 1e).

Mounted by app/css_app.py under /api/transfer/ next to the legacy endpoints (unchanged). Every response is a JSON
object with "ok" and, on refusal, "error": {"code", "message"}; job status always comes from the journal.

GET  jobs?state=&limit=          list of job summaries (newest first)
GET  job?id=                     summary + files + skipped items + last events
GET  assess?id=                  Phase 1c read-only recovery assessment (hashes files; may take time)
GET  workers                     worker pool status
GET  vault_check?path=           1e: read-only Vault verification (default: the configured Vault)
POST jobs/create   {operation: archive|stage|move, items: [{src, dst}], study_id?, keep_previous?, request_id?}
POST jobs/pause    {job_id}      cooperative pause at the next safe boundary
POST jobs/resume   {job_id}      Phase 1c resume (decision recorded) - background
POST jobs/discard  {job_id}      Phase 1c discard (decision recorded) - background
POST jobs/cancel   {job_id}      only for a job that has not started (nothing written)
"""
import json
import time
from typing import Any, Dict, Optional

from .journal import DuplicateRequest
from .models import JobState, TERMINAL_JOB_STATES
from .service import TransferRefused
from ..safety import is_simple_name

CREATE_OPS = ("archive", "stage", "move")
MAX_ITEMS = 1000


def _err(code: str, message: str) -> Dict[str, Any]:
    return dict(ok=False, error=dict(code=code, message=message))


def job_summary(job: Dict[str, Any], pool=None) -> Dict[str, Any]:
    tb, db, pb = job["total_bytes"] or 0, job["done_bytes"] or 0, job["phase_bytes"] or 0
    state = job["state"]
    terminal = JobState(state) in TERMINAL_JOB_STATES
    pct = 100.0 if state in ("completed", "completed_with_retained_sources") else (round(100.0 * db / tb, 1) if tb else 0.0)
    err = None
    if job["error"] and state in ("failed", "needs_attention", "interrupted", "paused", "recovering", "rolling_back"):
        err = dict(code=state, message=job["error"])
    return dict(job_id=job["job_id"], operation=job["operation"], study_id=job["study_id"], commit_mode=job["commit_mode"],
                state=state, terminal=terminal, created_at=job["created_at"], updated_at=job["updated_at"],
                progress=dict(files_done=job["done_files"], files_total=job["total_files"], bytes_committed=db,
                              bytes_staged=pb, bytes_total=tb, percent_committed=pct, current_file=job["current_file"]),
                control=job.get("control"), recovery_decision=job.get("recovery_decision"),
                running=bool(pool and pool.is_running(job["job_id"])),
                heartbeat_age_s=round(time.time() - job["heartbeat"], 1) if job.get("heartbeat") else None,
                error=err)


def handle_get(op: str, q: Dict[str, str], pool) -> Optional[Dict[str, Any]]:
    """None if op is not a 1d endpoint (the caller falls back to the legacy ops)"""
    jn = pool._svc.journal
    if op == "jobs":
        st = q.get("state")
        try:
            states = [JobState(s) for s in st.split(",")] if st else None
        except ValueError:
            return _err("bad_request", f"unknown state in {st!r}")
        try:
            limit = max(1, min(500, int(q.get("limit", 100))))
        except ValueError:
            return _err("bad_request", "limit must be a number")
        return dict(ok=True, jobs=[job_summary(j, pool) for j in jn.list_jobs(states, limit=limit)])
    if op in ("job", "assess"):
        jid = q.get("id", "")
        if not is_simple_name(jid):
            return _err("bad_request", "invalid job id")
        job = jn.get_job(jid)
        if job is None:
            return _err("not_found", f"unknown job {jid}")
        if op == "assess":
            return dict(ok=True, assessment=pool._svc.assess(jid))
        spec = json.loads(job["spec_json"])
        files = [dict(seq=f["seq"], rel_path=f["rel_path"], size=f["size"], state=f["state"], error=f["error"],
                      attempt=f["attempt"], dst=f["committed_path"] or f["dst"]) for f in jn.get_files(jid)]
        events = jn.events(jid)[-50:]
        return dict(ok=True, job=job_summary(job, pool), files=files, skipped=spec.get("skipped", []),
                    events=[dict(ts=e["ts"], kind=e["kind"], seq=e["seq"], from_state=e["from_state"], to_state=e["to_state"],
                                 detail=json.loads(e["detail_json"]) if e["detail_json"] else None) for e in events])
    if op == "workers":
        return dict(ok=True, workers=pool.status())
    if op == "vault_check":                                   # 1e: read-only verification of the configured Vault
        from ..storage.vault_check import verify_vault
        return dict(ok=True, vault=verify_vault(q.get("path") or pool.vault or ""))
    return None


def handle_post(op: str, d: Dict[str, Any], pool) -> Optional[Dict[str, Any]]:
    if not isinstance(d, dict):
        return _err("bad_request", "JSON object expected")
    try:
        if op == "jobs/create":
            opn = d.get("operation")
            if opn not in CREATE_OPS:
                return _err("bad_request", f"operation must be one of {', '.join(CREATE_OPS)}")
            items = d.get("items")
            if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
                return _err("bad_request", f"items must be a list of 1-{MAX_ITEMS} {{src, dst}} objects")
            pairs = []
            for it in items:
                if not isinstance(it, dict) or not isinstance(it.get("src"), str) or not isinstance(it.get("dst"), str):
                    return _err("bad_request", "each item needs string src and dst")
                pairs.append((it["src"], it["dst"]))
            rid = d.get("request_id")
            if rid is not None and (not isinstance(rid, str) or not is_simple_name(rid) or len(rid) > 64):
                return _err("bad_request", "invalid request_id")
            res = pool.submit(opn, pairs, study_id=d.get("study_id"), keep_previous=d.get("keep_previous") is True,
                              request_id=rid)
            return dict(ok=True, **res)
        jid = d.get("job_id", "")
        if op in ("jobs/pause", "jobs/resume", "jobs/discard", "jobs/cancel"):
            if not isinstance(jid, str) or not is_simple_name(jid):
                return _err("bad_request", "invalid job_id")
            if pool._svc.journal.get_job(jid) is None:
                return _err("not_found", f"unknown job {jid}")
            fn = {"jobs/pause": pool.pause, "jobs/resume": pool.resume, "jobs/discard": pool.discard,
                  "jobs/cancel": pool.cancel_queued}[op]
            return dict(ok=True, **fn(jid))
    except DuplicateRequest as e:
        return dict(ok=True, job_id=e.job_id, duplicate=True)
    except TransferRefused as e:
        return _err("refused", str(e))
    return None
