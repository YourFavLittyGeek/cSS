"""uengine/transfer/workers.py - Phase 1d: background transfer workers (independent of the GUI).

TransferWorkerPool(project, vault).start()
  * The JOURNAL is the queue: QUEUED jobs are picked up in creation order; nothing lives only in memory except explicit
    recovery requests (resume / discard), and those are re-requestable because the job stays durably PAUSED /
    INTERRUPTED until a recovery actually runs.
  * One worker slot per destination DEVICE (st_dev): an external HDD is written strictly sequentially; jobs for
    different devices run in parallel. File-level exclusivity is still enforced by the service's per-study and
    per-destination locks, and duplicate execution by the per-job liveness lock (also across processes).
  * A worker never decides a job's outcome: status always comes from the journal. If a worker exits abnormally, the
    job's lock is free again and detect_interrupted() (1c) marks it INTERRUPTED - recovery is the user's decision.
  * pause(job) writes a cooperative request into the journal; the owner stops at its next safe boundary (PAUSED).
    resume(job) / discard(job) go through the Phase 1c recovery path (TransferService.resume / discard) - there is no
    second recovery mechanism.
  * shutdown(timeout) stops picking up work, asks every running job to pause, and waits. A job that has not reached a
    safe boundary when the process exits stays active in the journal and is detected as interrupted on next start.
"""
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from .journal import DuplicateRequest
from .models import JobState, TERMINAL_JOB_STATES
from ..safety import PathPolicy
from .service import TransferRefused, TransferService

J = JobState


def _device_of(path: str) -> int:
    p = path
    while p and not os.path.exists(p):
        p = os.path.dirname(p)
    try:
        return os.stat(p or "/").st_dev
    except OSError:
        return -1


class TransferWorkerPool:
    def __init__(self, project_base: str, vault_root: Optional[str] = None, *, poll_s: float = 0.25,
                 lock_timeout: float = 0.5, workers_per_device: int = 1):
        self.base, self.vault = project_base, vault_root
        self.poll_s, self.lock_timeout, self.per_device = poll_s, lock_timeout, max(1, int(workers_per_device))
        self._svc = TransferService(project_base, vault_root)            # dispatcher's own journal connection
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._running: Dict[str, Dict[str, Any]] = {}                    # job_id -> {thread, task, device, started}
        self._tasks: List[Dict[str, Any]] = []                           # explicit recovery requests
        self._thread: Optional[threading.Thread] = None
        self.history: List[Dict[str, Any]] = []                          # finished worker runs (diagnostics only)
        self.detected_at_start: List[str] = []

    # ------------------------------------------------------------------ lifecycle
    def set_vault(self, vault_root: Optional[str]) -> bool:
        """follow a changed Vault path (configured or created after start-up). New jobs and checks use it; a running
        job keeps the service it started with. The journal and locks live in the project, so they do not change."""
        v = vault_root or None
        with self._lock:
            if v == self.vault:
                return False
            self.vault = v
            self._svc.vault = os.path.abspath(v) if v else None
            self._svc.policy = PathPolicy(self.base, v)
        return True

    def start(self) -> "TransferWorkerPool":
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self
            self.detected_at_start = self._svc.detect_interrupted()      # owners provably dead -> INTERRUPTED (no disk change)
            self._stop.clear()
            self._thread = threading.Thread(target=self._dispatch, name="percival-transfer-dispatcher", daemon=True)
            self._thread.start()
        return self

    def shutdown(self, timeout: float = 15.0) -> Dict[str, Any]:
        """stop taking work, request a pause of every running job, wait for safe boundaries"""
        self._stop.set()
        self._wake.set()
        with self._lock:
            running = list(self._running)
        for job_id in running:
            try:
                self._svc.journal.request_control(job_id, "pause")
            except Exception:
                pass
        deadline = time.monotonic() + timeout
        for job_id in running:
            t = self._running.get(job_id, {}).get("thread")
            if t is not None:
                t.join(max(0.0, deadline - time.monotonic()))
        if self._thread:
            self._thread.join(max(0.0, deadline - time.monotonic()))
        still = [j for j, r in self._running.items() if r["thread"].is_alive()]
        states = {j: (self._svc.journal.get_job(j) or {}).get("state") for j in running}
        return dict(requested_pause=running, still_running=still, states=states)

    def close(self):
        self._svc.close()

    # ------------------------------------------------------------------ requests (all journal-backed)
    def submit(self, operation, items, study_id=None, mode=None, keep_previous=False, request_id: Optional[str] = None) -> Dict[str, Any]:
        try:                                                            # request_id: atomic idempotency (unique index)
            job_id = self._svc.submit(operation, items, study_id=study_id, mode=mode, keep_previous=keep_previous,
                                      request_id=request_id)
        except DuplicateRequest as d:
            return dict(job_id=d.job_id, duplicate=True, state=self._svc.journal.get_job(d.job_id)["state"])
        self._wake.set()
        return dict(job_id=job_id, duplicate=False, state=J.QUEUED.value)

    def pause(self, job_id: str) -> Dict[str, Any]:
        job = self._require(job_id)
        st = JobState(job["state"])
        if st == J.PAUSED:
            return dict(job_id=job_id, state=st.value, noop=True)
        if st == J.QUEUED:
            # never started: nothing on disk - pause by moving it out of the queue (durable)
            try:
                self._svc.journal.transition_job(job_id, J.PAUSED, expected=[J.QUEUED], detail={"paused_at": "queued"})
                return dict(job_id=job_id, state=J.PAUSED.value)
            except Exception:
                job = self._require(job_id)                             # the dispatcher took it meanwhile
                st = JobState(job["state"])
        if st in TERMINAL_JOB_STATES or st in (J.INTERRUPTED, J.NEEDS_ATTENTION, J.FAILED):
            raise TransferRefused(f"job {job_id} is {st.value}; there is nothing to pause")
        self._svc.journal.request_control(job_id, "pause")
        return dict(job_id=job_id, state=st.value, pause_requested=True)

    def resume(self, job_id: str) -> Dict[str, Any]:
        return self._request_recovery(job_id, "resume")

    def discard(self, job_id: str) -> Dict[str, Any]:
        return self._request_recovery(job_id, "discard")

    def cancel_queued(self, job_id: str) -> Dict[str, Any]:
        """a job that never started can be cancelled directly (nothing was written); anything else -> pause + discard"""
        try:
            self._svc.journal.transition_job(job_id, J.CANCELLED, expected=[J.QUEUED], detail={"cancelled": "before start"})
        except Exception:
            raise TransferRefused(f"job {job_id} is no longer queued; pause it and discard it instead")
        return dict(job_id=job_id, state=J.CANCELLED.value)

    def _request_recovery(self, job_id: str, decision: str) -> Dict[str, Any]:
        job = self._require(job_id)
        st = JobState(job["state"])
        if st in TERMINAL_JOB_STATES:
            return dict(job_id=job_id, state=st.value, noop=True)
        if st not in (J.PAUSED, J.INTERRUPTED, J.NEEDS_ATTENTION, J.FAILED):
            raise TransferRefused(f"job {job_id} is {st.value}; {decision} is possible only for paused / interrupted jobs")
        if job["recovery_decision"] and job["recovery_decision"] != decision:
            raise TransferRefused(f"job {job_id} is being recovered with '{job['recovery_decision']}'")
        with self._lock:
            # de-duplicate against PENDING requests only: the previous worker of a just-paused job may still be
            # finishing; the dispatcher starts the recovery only after that worker has exited (never concurrently)
            if any(t["job_id"] == job_id for t in self._tasks):
                return dict(job_id=job_id, state=st.value, already_requested=True)
            self._tasks.append(dict(job_id=job_id, action=decision))
        self._wake.set()
        return dict(job_id=job_id, state=st.value, requested=decision)

    def _require(self, job_id):
        job = self._svc.journal.get_job(job_id)
        if job is None:
            raise TransferRefused(f"unknown job {job_id}")
        return job

    def is_running(self, job_id: str) -> bool:
        with self._lock:
            r = self._running.get(job_id)
            return bool(r and r["thread"].is_alive())

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(alive=bool(self._thread and self._thread.is_alive()), stopping=self._stop.is_set(),
                        running=[dict(job_id=j, action=r["action"], device=r["device"], since=r["started"])
                                 for j, r in self._running.items() if r["thread"].is_alive()],
                        pending_requests=list(self._tasks), workers_per_device=self.per_device,
                        detected_interrupted_at_start=self.detected_at_start)

    # ------------------------------------------------------------------ dispatcher / workers
    def _device(self, job_id: str) -> int:
        files = self._svc.journal.get_files(job_id)
        if files:
            return _device_of(os.path.dirname(files[0]["dst"]))
        spec = json.loads(self._svc.journal.get_job(job_id)["spec_json"])
        roots = spec.get("roots") or [{}]
        return _device_of(roots[0].get("dst", "/"))

    def _busy_devices(self) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for r in self._running.values():
            if r["thread"].is_alive():
                out[r["device"]] = out.get(r["device"], 0) + 1
        return out

    def _dispatch(self):
        while not self._stop.is_set():
            try:
                self._reap()
                with self._lock:
                    candidates = [dict(t) for t in self._tasks] + [
                        dict(job_id=j["job_id"], action="run")
                        for j in sorted(self._svc.journal.list_jobs([J.QUEUED], limit=1000), key=lambda j: j["created_at"])]
                    busy = self._busy_devices()
                    for c in candidates:
                        r = self._running.get(c["job_id"])
                        if r is not None:
                            if r["thread"].is_alive():
                                continue                            # its previous worker is still finishing
                            self._running.pop(c["job_id"], None)
                        dev = self._device(c["job_id"])
                        if busy.get(dev, 0) >= self.per_device:
                            continue
                        if c["action"] != "run":
                            self._tasks = [t for t in self._tasks if t["job_id"] != c["job_id"]]
                        t = threading.Thread(target=self._work, args=(c["job_id"], c["action"]),
                                             name=f"percival-transfer-{c['job_id']}", daemon=True)
                        self._running[c["job_id"]] = dict(thread=t, action=c["action"], device=dev, started=time.time())
                        busy[dev] = busy.get(dev, 0) + 1
                        t.start()
            except Exception:
                pass                                                    # the dispatcher never dies on one bad job
            self._wake.wait(self.poll_s)
            self._wake.clear()

    def _reap(self):
        with self._lock:
            for j in [j for j, r in self._running.items() if not r["thread"].is_alive()]:
                self._running.pop(j, None)

    def _work(self, job_id: str, action: str):
        svc = None
        outcome: Dict[str, Any] = dict(job_id=job_id, action=action, started=time.time())
        try:
            svc = TransferService(self.base, self.vault)
            if action == "run":
                rep = svc.run(job_id, lock_timeout=self.lock_timeout)
            elif action == "resume":
                rep = svc.resume(job_id, lock_timeout=self.lock_timeout)
            else:
                rep = svc.discard(job_id, lock_timeout=self.lock_timeout)
            outcome["returned_state"] = rep.get("state")
        except TransferRefused as e:                                    # e.g. already running in another process
            outcome["refused"] = str(e)
        except BaseException as e:                                      # worker crash: the journal decides, not us
            outcome["crashed"] = f"{type(e).__name__}: {e}"
        finally:
            try:
                if svc is not None:
                    # if the job is still in an active state now that its lock is released, its owner is gone:
                    # 1c detection marks it INTERRUPTED (never "completed" because the worker exited)
                    job = svc.journal.get_job(job_id)
                    if job and JobState(job["state"]) not in TERMINAL_JOB_STATES:
                        svc.detect_interrupted()
                    outcome["journal_state"] = (svc.journal.get_job(job_id) or {}).get("state")
                    svc.close()
            except Exception as e:
                outcome["post_check_error"] = repr(e)
            outcome["ended"] = time.time()
            with self._lock:
                self.history.append(outcome)
            self._wake.set()
