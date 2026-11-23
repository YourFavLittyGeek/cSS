"""uengine/transfer/service.py - journal-backed transfer jobs (1b) with write-ahead logging and crash recovery (1c).

Normal run (1b semantics, 1c write-ahead):
  submit   plan every item (links never followed, metadata / artifacts skipped and reported), Phase 0 policy on every
           source and destination, exFAT destinations refused, duplicate destinations refused, job recorded (queued).
  run      job lock FIRST (proves liveness), PREPARING, destination + study locks, pipeline-active refusal,
           NEVER_OVERWRITE conflicts -> NEEDS_ATTENTION with nothing written.
           A: stage + verify every file (part identity journaled before any data). Failure -> undo own parts -> FAILED.
           B: commit every file; the intent (target, preserved path, old identity) is journaled BEFORE any rename.
              Failure -> ROLLING_BACK, every own commit undone (identity + hash checked) -> FAILED / NEEDS_ATTENTION.
           C: move - a source is removed only after destination AND source are re-verified by hash; intent first.
           D: previous versions removed only after the whole job succeeded; intent first.

Recovery (1c, never automatic):
  detect_interrupted()  jobs in an active state whose owner is provably dead (its job lock is free) -> INTERRUPTED.
                        Changes nothing on disk.
  assess(job)           read-only, per-file classification verified by identity AND hash (_classify): ambiguous items,
                        unrecognized temporary files and unavailable volumes are reported.
  resume(job)           refused if anything is ambiguous or unavailable. The decision is persisted (RECOVERING,
                        'resume') before any change; finishes the job (re-stage what is missing, commit, remove move
                        sources, finalize). A non-ambiguous failure (disk full, permission) -> INTERRUPTED, retryable.
  discard(job)          decision persisted ('discard'); undoes only what is provably this job's own (published files,
                        moved-aside previous versions, own .part files, empty folders it created). Never touches
                        sources, foreign / changed files or unrecognized temporary files. A move destination whose
                        source was already removed is KEPT (it is the only copy). -> CANCELLED / NEEDS_ATTENTION.
  Both are idempotent: on a terminal job they are a no-op; after a crash they continue from the journal, and every
  step re-checks its precondition, so repeating a step is harmless.
"""
import json
import os
import secrets
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import copier as CP
from .crashpoints import crash
from .journal import TransferJournal
from .locks import LockTimeout, TransferLocks, dst_key, study_key, study_processing_active
from .models import (ACTIVE_JOB_STATES, DEFAULT_COMMIT_MODE, TERMINAL_JOB_STATES, CommitMode, FileState, JobState,
                     Operation)
from .tree import plan_tree
from ..safety import PathPolicy, SafetyError, validate_study_code

F, J = FileState, JobState
PIPELINE_GUARDED_OPS = {Operation.ARCHIVE, Operation.SYNC, Operation.STAGE}
PUBLISH_STATES = (F.COMMITTING.value, F.COMMITTED.value)


class TransferRefused(RuntimeError):
    """the job (or recovery request) was refused before anything was recorded or written"""


class PauseRequested(BaseException):
    """1d: a cooperative pause was requested and this is a safe boundary (BaseException: never caught as a failure)"""

    def __init__(self, where: str):
        super().__init__(where)
        self.where = where


_PAUSE_EXC = (PauseRequested, CP.CopyPaused)


def _job_id(op: Operation, study: Optional[str]) -> str:
    return f"{op.value}-{study or 'x'}-{time.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"[:56]


def job_key(job_id: str) -> str:
    return f"job:{job_id}"


def _jd(x) -> Optional[str]:
    return json.dumps(list(x)) if x is not None else None


def _jl(s) -> Optional[tuple]:
    return tuple(json.loads(s)) if s else None


def _intent(rec) -> dict:
    try:
        return json.loads(rec["intent"]) if rec["intent"] else {}
    except ValueError:
        return {}


def _ident(path) -> Optional[tuple]:
    try:
        st = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    return (st.st_size, st.st_mtime_ns, st.st_ino)


def _sha(path) -> Optional[str]:
    try:
        return CP._hash_file(path)[0]
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError, PermissionError):
        return None


class TransferService:
    def __init__(self, project_base: str, vault_root: Optional[str] = None):
        self.base = os.path.abspath(project_base)
        self.vault = os.path.abspath(vault_root) if vault_root else None
        self.policy = PathPolicy(self.base, self.vault)
        self.journal = TransferJournal(self.base, self.vault)
        self.locks = TransferLocks(self.base, self.vault)

    def close(self):
        self.journal.close()

    # ================================================================================================= submit
    def submit(self, operation, items: Sequence[Tuple[str, str]], study_id: Optional[str] = None,
               mode: Optional[CommitMode] = None, keep_previous: bool = False, request_id: Optional[str] = None) -> str:
        op = Operation(operation)
        mode = CommitMode(mode or DEFAULT_COMMIT_MODE[op])
        if study_id is not None:
            try:
                validate_study_code(study_id)
            except SafetyError as e:
                raise TransferRefused(str(e))
        if not items:
            raise TransferRefused("nothing to transfer")
        files, empty_dirs, skipped, roots = [], [], [], []
        seen = {}
        for i, (src, dst) in enumerate(items):
            try:
                if op == Operation.MOVE:
                    self.policy.check_modify(src)
                self.policy.check_source(src)
                plan = plan_tree(src, dst)
            except (SafetyError, ValueError) as e:
                raise TransferRefused(f"item {i}: {e}")
            roots.append(dict(src=plan.src_root, dst=plan.dst_root, is_file=plan.is_file))
            for s in plan.skipped:
                skipped.append(dict(s, item=i))
            for d in plan.empty_dirs:
                p = os.path.join(plan.dst_root, d) if d else plan.dst_root
                try:
                    self.policy.check_write_target(p)
                except SafetyError as e:
                    raise TransferRefused(f"folder {p}: {e}")
                empty_dirs.append(p)
            for f in plan.files:
                try:
                    self.policy.check_source(f.src)
                    d = self.policy.check_write_target(f.dst)
                except SafetyError as e:
                    raise TransferRefused(f"{f.rel}: {e}")
                k = d.lower()
                if k in seen:
                    raise TransferRefused(f"two files of this job would write the same destination {d} "
                                          f"({seen[k]} and {f.src}; destination names are compared case-insensitively)")
                seen[k] = f.src
                files.append(dict(rel_path=f.rel, src=f.src, dst=d, size=f.size))
        for d in {os.path.dirname(f["dst"]) for f in files} | set(empty_dirs):
            try:
                CP.preflight_destination(os.path.join(d, "x"))
            except CP.CopyRefused as e:                  # exFAT (no exclusive commit) or a read-only volume
                raise TransferRefused(str(e))
        job_id = _job_id(op, study_id)
        self.journal.create_job(job_id, op.value, mode.value, files, study_id=study_id, request_id=request_id,
                                spec=dict(roots=roots, empty_dirs=empty_dirs, skipped=skipped, keep_previous=bool(keep_previous)))
        return job_id

    def transfer(self, operation, items, study_id=None, mode=None, keep_previous=False, **run_kw) -> Dict[str, Any]:
        return self.run(self.submit(operation, items, study_id=study_id, mode=mode, keep_previous=keep_previous), **run_kw)

    # ================================================================================================= normal run
    def _report(self, job_id) -> Dict[str, Any]:
        job = self.journal.get_job(job_id)
        spec = json.loads(job["spec_json"])
        return dict(job_id=job_id, operation=job["operation"], commit_mode=job["commit_mode"], study_id=job["study_id"],
                    committed=[], skipped_identical=[], conflicts=[], skipped=spec.get("skipped", []), retained_sources=[],
                    preserved_kept=[], kept_only_copy=[], left_untouched=[], errors=[], state=None)

    def _keys(self, job, files) -> List[str]:
        spec = json.loads(job["spec_json"])
        keys = [dst_key(f["dst"]) for f in files] + [dst_key(d) for d in spec.get("empty_dirs", [])]
        if job["study_id"]:
            keys.append(study_key(job["study_id"]))
        return keys

    def run(self, job_id: str, *, lock_timeout: float = 30.0, chunk_size: int = CP.CHUNK, _hooks: Optional[dict] = None) -> Dict[str, Any]:
        hooks = _hooks or {}
        job = self.journal.get_job(job_id)
        if job is None:
            raise TransferRefused(f"unknown job {job_id}")
        rep = self._report(job_id)
        try:
            with self.locks.hold([job_key(job_id)], timeout=lock_timeout):     # liveness lock FIRST
                self.journal.transition_job(job_id, J.PREPARING, expected=[J.QUEUED], owner_pid=os.getpid())
                files = self.journal.get_files(job_id)
                try:
                    with self.locks.hold(self._keys(job, files), timeout=lock_timeout):
                        return self._run_locked(job_id, Operation(job["operation"]), CommitMode(job["commit_mode"]),
                                                json.loads(job["spec_json"]), files, rep, chunk_size, hooks)
                except LockTimeout as e:
                    return self._end(job_id, J.FAILED, rep, f"busy: {e}")
        except LockTimeout as e:
            raise TransferRefused(f"job {job_id} is already running: {e}")

    # ---------------------------------------------------------------- 1d cooperative pause
    def _checkpoint(self, job_id: str, where: str) -> None:
        """a SAFE boundary: everything before it is journaled; raise PauseRequested if a pause was requested"""
        crash(f"checkpoint.{where}")
        if self.journal.get_control(job_id) == "pause":
            raise PauseRequested(where)

    def _chunk_control(self, job_id: str):
        """copier control: checked between chunks (the .part identity is already journaled)"""
        last = [0.0, None]

        def control():
            now = time.monotonic()
            if now - last[0] >= 0.05:
                last[0], last[1] = now, self.journal.get_control(job_id)
            return "pause" if last[1] == "pause" else None
        return control

    def _pause(self, job_id: str, rep, where: str):
        """the job stops at a safe boundary: nothing is rolled back, every file stays in a classifiable journaled state;
        the job continues only through 1c recovery (resume / discard)"""
        self.journal.set_job(job_id, control=None)
        self.journal.transition_job(job_id, J.PAUSED, detail={"paused_at": where})
        rep.update(state=J.PAUSED.value, ok=False, paused_at=where)
        return rep

    def _volume_gone(self, job_id, rep, exc):
        """a source / destination volume disappeared: no rollback is attempted (it could not succeed and would only
        leave half-undone files) - the job is INTERRUPTED for 1c recovery after the volume is back"""
        job = self.journal.get_job(job_id)
        gone = self._unavailable(job, self.journal.get_files(job_id))
        if not gone:
            return None
        rep["errors"].append(f"{type(exc).__name__}: {exc}; " + "; ".join(gone))
        self.journal.transition_job(job_id, J.INTERRUPTED, error="volume unavailable: " + "; ".join(gone))
        rep.update(state=J.INTERRUPTED.value, ok=False)
        return rep

    def _end(self, job_id, state, rep, error=None):
        if error:
            rep["errors"].append(error)
        self.journal.transition_job(job_id, state, error=error, detail={k: len(v) for k, v in rep.items() if isinstance(v, list)})
        rep["state"] = JobState(state).value
        rep["ok"] = state in (J.COMPLETED, J.COMPLETED_WITH_RETAINED_SOURCES)
        return rep

    def _rec(self, job_id, seq) -> dict:
        return self.journal.get_files(job_id)[seq]

    def _makedirs(self, job_id: str, d: str) -> List[str]:
        """create d (and missing parents) through the policy; every folder is journaled BEFORE it is created"""
        made, p, missing = [], d, []
        while p and not os.path.isdir(p):
            missing.append(p)
            p = os.path.dirname(p)
        for m in reversed(missing):
            self.policy.check_write_target(m)
            self.journal.add_created_dir(job_id, m)
            crash("mkdir.after_record")
            try:
                os.mkdir(m)
                made.append(m)
            except FileExistsError:
                if not os.path.isdir(m):
                    raise
        return made

    @staticmethod
    def _tag(job_id, rec):
        a = int(rec["attempt"] or 0)
        return job_id if a == 0 else f"{job_id}-r{a}"

    def _stage_one(self, job_id, f, mode, chunk_size, progress=None, control=None):
        """write-ahead staging: COPYING(part path) -> part identity journaled on creation -> STAGED -> VERIFIED"""
        jn, seq = self.journal, f["seq"]
        tag = self._tag(job_id, f)
        self._makedirs(job_id, os.path.dirname(f["dst"]))
        jn.transition_file(job_id, seq, F.COPYING, part_path=f"{f['dst']}.part-{tag}", part_identity=None,
                           part_sha256=None, intent=json.dumps({"step": "stage"}))
        crash("stage.before_copy")
        r = CP.stage_file(f["src"], f["dst"], policy=self.policy, job_tag=tag, mode=mode, chunk_size=chunk_size,
                          progress=progress, control=control,
                          on_created=lambda p, i: jn.update_file(job_id, seq, part_identity=_jd(i)))
        if isinstance(r, CP.CopyResult):
            if r.status == "skipped_identical":
                jn.transition_file(job_id, seq, F.SKIPPED_IDENTICAL, src_sha256=r.src_sha256, dst_sha256=r.dst_sha256, intent=None)
            else:
                jn.transition_file(job_id, seq, F.CONFLICT, src_sha256=r.src_sha256, dst_sha256=r.dst_sha256, intent=None,
                                   error="destination exists with different content")
            return r
        jn.transition_file(job_id, seq, F.STAGED, src_sha256=r.src_sha256, src_identity=_jd(r.src_identity))
        jn.transition_file(job_id, seq, F.VERIFIED, part_sha256=r.part_sha256, part_identity=_jd(r.part_identity), intent=None)
        crash("stage.after_verified")
        return r

    def _staged_from(self, job_id, rec) -> CP.StagedFile:
        return CP.StagedFile(rec["src"], rec["dst"], rec["part_path"], self._tag(job_id, rec), rec["size"], rec["src_sha256"],
                             rec["part_sha256"], _jl(rec["src_identity"]), _jl(rec["part_identity"]), "", True)

    def _commit_one(self, job_id, f, staged, mode, rep):
        """write-ahead commit: COMMITTING (target, preserved path, old identity) is journaled before any rename"""
        jn, seq = self.journal, f["seq"]
        first = [True]

        def on_intent(d):
            fields = dict(intent=json.dumps({"step": "publish", "target": d["target"]}), preserved_path=d["preserved_path"],
                          old_identity=_jd(d["old_identity"]), preserved_state="planned" if d["preserved_path"] else "none")
            if first[0]:
                jn.transition_file(job_id, seq, F.COMMITTING, **fields)
                first[0] = False
            else:
                jn.update_file(job_id, seq, **fields)
            crash("commit.after_intent")
        r = CP.commit_staged(staged, mode, policy=self.policy, on_intent=on_intent)
        if r.status == "committed":
            jn.transition_file(job_id, seq, F.COMMITTED, dst_sha256=r.dst_sha256, committed_path=r.dst,
                               dst_identity=_jd(r.dst_identity), preserved_state="moved" if r.preserved_path else "none", intent=None)
            crash("commit.after_record")
        elif r.status == "skipped_identical":
            jn.transition_file(job_id, seq, F.SKIPPED_IDENTICAL, dst_sha256=r.dst_sha256, intent=None)
            rep["skipped_identical"].append(r.dst)
        else:
            jn.transition_file(job_id, seq, F.CONFLICT, intent=None, error="destination created by someone else during commit")
            rep["conflicts"].append(dict(rel=f["rel_path"], dst=r.dst, reason="created by someone else during commit"))
            raise CP.CopyError(f"{r.dst} was created by someone else during the commit; nothing was overwritten")
        return r

    def _run_locked(self, job_id, op, mode, spec, files, rep, chunk_size, hooks):
        jn = self.journal
        study = jn.get_job(job_id)["study_id"]
        if study and op in PIPELINE_GUARDED_OPS and study_processing_active(self.base, study):
            return self._end(job_id, J.FAILED, rep, f"study {study} is being processed by the pipeline; "
                                                    f"{op.value} refused until the run has finished")
        todo = []
        for f in files:
            if os.path.lexists(f["dst"]) and mode == CommitMode.NEVER_OVERWRITE:
                if not os.path.isfile(f["dst"]) or os.path.islink(f["dst"]):
                    rep["conflicts"].append(dict(rel=f["rel_path"], dst=f["dst"], reason="destination is not a regular file"))
                    jn.transition_file(job_id, f["seq"], F.CONFLICT, error="destination is not a regular file")
                    continue
                s, d = _sha(f["src"]), _sha(f["dst"])
                if s == d:
                    jn.transition_file(job_id, f["seq"], F.SKIPPED_IDENTICAL, src_sha256=s, dst_sha256=d)
                    rep["skipped_identical"].append(f["dst"])
                else:
                    jn.transition_file(job_id, f["seq"], F.CONFLICT, src_sha256=s, dst_sha256=d,
                                       error="destination exists with different content")
                    rep["conflicts"].append(dict(rel=f["rel_path"], dst=f["dst"], src_sha256=s, dst_sha256=d))
                continue
            todo.append(f)
        if rep["conflicts"]:
            return self._end(job_id, J.NEEDS_ATTENTION, rep, f"{len(rep['conflicts'])} destination file(s) exist with different "
                                                            f"content; nothing was written (archives are never overwritten)")
        # ---------------------------------------------------------------- A: stage + verify everything
        staged: List[Tuple[dict, CP.StagedFile]] = []
        done_bytes = 0
        try:
            if todo:
                jn.transition_job(job_id, J.COPYING)
            for f in todo:
                self._checkpoint(job_id, "before_stage")
                jn.update_progress(job_id, current_file=f["rel_path"])
                if hooks.get("before_stage"):
                    hooks["before_stage"](f)
                state = {"phase": "copying", "t": 0.0}

                def progress(phase, n, _st=state, _base=done_bytes):
                    if phase != _st["phase"]:
                        nxt = {"flushing": J.FLUSHING, "verifying": J.VERIFYING}.get(phase)
                        if nxt:
                            jn.transition_job(job_id, nxt)
                        _st["phase"] = phase
                    elif phase == "copying" and time.monotonic() - _st["t"] >= 0.5:     # truthful, throttled progress
                        _st["t"] = time.monotonic()
                        jn.update_progress(job_id, phase_bytes=_base + n)
                r = self._stage_one(job_id, self._rec(job_id, f["seq"]), mode, chunk_size, progress,
                                    control=self._chunk_control(job_id))
                if isinstance(r, CP.CopyResult):
                    if r.status == "skipped_identical":
                        rep["skipped_identical"].append(r.dst)
                        continue
                    rep["conflicts"].append(dict(rel=f["rel_path"], dst=r.dst))
                    raise CP.CopyError(f"{r.dst} appeared with different content during the job")
                staged.append((f, r))
                done_bytes += r.size
                jn.update_progress(job_id, phase_bytes=done_bytes)
                if state["phase"] == "verifying":
                    jn.transition_job(job_id, J.COPYING)
        except _PAUSE_EXC as e:
            return self._pause(job_id, rep, getattr(e, "where", "during_copy"))
        except BaseException as e:
            gone = self._volume_gone(job_id, rep, e)
            if gone:
                return gone
            unsafe = self._abort_run(job_id, e, rep)
            state = J.NEEDS_ATTENTION if (rep["conflicts"] or unsafe) else J.FAILED
            return self._end(job_id, state, rep, f"{type(e).__name__}: {e} - no destination was changed")
        # ---------------------------------------------------------------- B: commit everything (or nothing)
        try:
            self._checkpoint(job_id, "before_commit_phase")
        except PauseRequested as e:
            return self._pause(job_id, rep, e.where)
        jn.transition_job(job_id, J.COMMITTING)
        committed: List[Tuple[dict, CP.CopyResult]] = []
        try:
            for d in sorted(set(spec.get("empty_dirs", [])) | {os.path.dirname(s.dst) for _, s in staged}):
                self._makedirs(job_id, d)
            for i, (f, s) in enumerate(staged):
                if i:
                    self._checkpoint(job_id, "between_commits")
                if hooks.get("before_commit"):
                    hooks["before_commit"](i, f)
                r = self._commit_one(job_id, f, s, mode, rep)
                if r.status == "committed":
                    committed.append((f, r))
                    jn.update_progress(job_id, done_files=len(committed), done_bytes=sum(x.size for _, x in committed))
        except PauseRequested as e:
            return self._pause(job_id, rep, e.where)
        except BaseException as e:
            gone = self._volume_gone(job_id, rep, e)
            if gone:
                return gone
            unsafe = self._abort_run(job_id, e, rep)
            if unsafe or rep["conflicts"]:
                return self._end(job_id, J.NEEDS_ATTENTION, rep, f"{type(e).__name__}: {e}; rollback "
                                                                f"{'INCOMPLETE - see the job report' if unsafe else 'complete'}")
            return self._end(job_id, J.FAILED, rep, f"{type(e).__name__}: {e} - all commits of this job were rolled back")
        rep["committed"] = [r.dst for _, r in committed]
        # ---------------------------------------------------------------- C / D (all commits done and recorded)
        final = J.COMPLETED
        try:
            if op == Operation.MOVE:
                self._checkpoint(job_id, "before_remove_sources")
                jn.transition_job(job_id, J.REMOVING_SOURCES)
                if hooks.get("before_remove_sources"):
                    hooks["before_remove_sources"]()
                final = self._remove_sources(job_id, spec, rep)
            self._checkpoint(job_id, "before_finalize")
            self._finalize(job_id, spec, rep)
        except PauseRequested as e:
            return self._pause(job_id, rep, e.where)
        except BaseException as e:
            # every commit is recorded; only clean-up remains - resumable through 1c, never rolled back here
            rep["errors"].append(f"{type(e).__name__}: {e}")
            jn.transition_job(job_id, J.INTERRUPTED, error=f"after commit: {type(e).__name__}: {e}")
            rep.update(state=J.INTERRUPTED.value, ok=False)
            return rep
        return self._end(job_id, final, rep)

    def _abort_run(self, job_id, exc, rep) -> bool:
        """normal-run failure: ROLLING_BACK, undo every file of this job (reverse), remove its empty folders"""
        jn = self.journal
        jn.transition_job(job_id, J.ROLLING_BACK, error=f"{type(exc).__name__}: {exc}")
        unsafe = False
        for rec in reversed(jn.get_files(job_id)):
            try:
                out = self._undo_file(job_id, rec, rep)
            except Exception as e:
                # audit: a failure DURING rollback (permission, I/O) never escapes and never guesses: the file keeps its
                # journaled ROLLING_BACK intent, nothing unproven is deleted, and the job needs a human / 1c discard
                rep["errors"].append(f"rollback of {rec['rel_path']} could not be completed: {type(e).__name__}: {e}")
                out = "unsafe"
            # a committed file changed by someone else during the failing job was left in place: report it, not "failed"
            unsafe |= out in ("unsafe", "kept")
        self._remove_created_dirs(job_id)
        return unsafe

    # ================================================================================================= shared steps
    def _remove_sources(self, job_id, spec, rep):
        """move: remove a source only after destination AND source are re-verified by hash; intent first"""
        jn, retained = self.journal, False
        for rec in jn.get_files(job_id):
            if rec["state"] == F.SOURCE_REMOVED.value:
                continue
            if rec["state"] == F.REMOVING_SOURCE.value and not os.path.lexists(rec["src"]):
                jn.transition_file(job_id, rec["seq"], F.SOURCE_REMOVED, intent=None)
                continue
            if rec["state"] not in (F.COMMITTED.value, F.REMOVING_SOURCE.value):
                continue
            ok = (_ident(rec["committed_path"]) == _jl(rec["dst_identity"]) and _sha(rec["committed_path"]) == rec["src_sha256"]
                  and not os.path.islink(rec["src"]) and _ident(rec["src"]) == _jl(rec["src_identity"])
                  and _sha(rec["src"]) == rec["src_sha256"])
            if ok:
                try:
                    self.policy.check_modify(rec["src"])
                    if rec["state"] != F.REMOVING_SOURCE.value:
                        jn.transition_file(job_id, rec["seq"], F.REMOVING_SOURCE, intent=json.dumps({"step": "remove_source"}))
                    crash("move.after_intent")
                    os.remove(rec["src"])
                    crash("move.after_remove")
                    jn.transition_file(job_id, rec["seq"], F.SOURCE_REMOVED, intent=None)
                    continue
                except (SafetyError, OSError) as e:
                    rep["errors"].append(f"source kept {rec['src']}: {e}")
            if rec["state"] == F.REMOVING_SOURCE.value or self._rec(job_id, rec["seq"])["state"] == F.REMOVING_SOURCE.value:
                jn.transition_file(job_id, rec["seq"], F.COMMITTED, intent=None, error="source retained: changed after the copy")
            else:
                jn.update_file(job_id, rec["seq"], error="source retained: changed after the copy")
            retained = True
            rep["retained_sources"].append(rec["src"])
        for s in spec.get("skipped", []):
            retained = True
            root = spec["roots"][s["item"]]["src"]
            rep["retained_sources"].append(os.path.join(root, s["rel"]) if not spec["roots"][s["item"]]["is_file"] else root)
        for root in [x["src"] for x in spec.get("roots", []) if not x["is_file"]]:
            for r_, ds, fs in os.walk(root, topdown=False, followlinks=False):
                try:
                    if not os.listdir(r_):
                        self.policy.check_modify(r_)
                        os.rmdir(r_)
                except (SafetyError, OSError):
                    pass
        return J.COMPLETED_WITH_RETAINED_SOURCES if retained else J.COMPLETED

    def _finalize(self, job_id, spec, rep):
        """remove previous versions moved aside by this job - only now (job verified), intent first, identity-checked"""
        jn = self.journal
        for rec in jn.get_files(job_id):
            if rec["preserved_state"] not in ("moved", "removing") or not rec["preserved_path"]:
                continue
            if rec["state"] not in (F.COMMITTED.value, F.SOURCE_REMOVED.value):
                continue
            if spec.get("keep_previous"):
                rep["preserved_kept"].append(rec["preserved_path"])
                continue
            jn.update_file(job_id, rec["seq"], preserved_state="removing")
            crash("finalize.after_intent")
            res = CP.remove_if_identity(rec["preserved_path"], _jl(rec["old_identity"]), policy=self.policy)
            crash("finalize.after_remove")
            if res in ("removed", "absent"):
                jn.update_file(job_id, rec["seq"], preserved_state="removed")
            else:
                jn.update_file(job_id, rec["seq"], preserved_state="moved", error="previous version changed; kept")
                rep["preserved_kept"].append(rec["preserved_path"])
                rep["errors"].append(f"previous version kept at {rec['preserved_path']}: it changed after being moved aside")

    def _own_part(self, rec) -> str:
        """'own' (the .part this job created, identity-matched), 'absent', or 'unrecognized' (never touched)"""
        p = rec["part_path"]
        if not p or not os.path.lexists(p):
            return "absent"
        ident, rec_ident = _ident(p), _jl(rec["part_identity"])
        if rec_ident is None or os.path.islink(p) or not os.path.isfile(p):
            return "unrecognized"
        if rec["part_sha256"] is None:                    # partial: still the inode this job created with O_EXCL
            return "own" if ident and ident[2] == rec_ident[2] else "unrecognized"
        return "own" if ident == rec_ident else "unrecognized"

    def _remove_own_part(self, job_id, rec, rep) -> None:
        own = self._own_part(rec)
        if own == "own":
            self.journal.update_file(job_id, rec["seq"], intent=json.dumps(dict(_intent(rec), discard_part=rec["part_path"])))
            crash("part.after_intent")
            try:
                self.policy.check_write_target(rec["part_path"])
                os.remove(rec["part_path"])
            except FileNotFoundError:
                pass
        elif own == "unrecognized":
            rep["left_untouched"].append(dict(path=rec["part_path"], reason="unrecognized temporary file (not provably this job's own)"))

    def _undo_file(self, job_id, rec, rep) -> str:
        """undo one file of this job (normal rollback and discard share this). Write-ahead: ROLLING_BACK first, the intent
        keeps the publish target and the state it came from. Removes only what is provably this job's own (identity AND
        hash); restores a moved-aside previous version exclusively.
        -> 'done' | 'kept' (foreign file or only copy left in place) | 'unsafe' (a human must look)"""
        jn, seq, st = self.journal, rec["seq"], rec["state"]
        if st == F.SOURCE_REMOVED.value or (st == F.REMOVING_SOURCE.value and not os.path.lexists(rec["src"])):
            if st == F.REMOVING_SOURCE.value:
                jn.transition_file(job_id, seq, F.SOURCE_REMOVED, intent=None)
            rep["kept_only_copy"].append(rec["committed_path"])
            return "kept"
        if st in (F.PENDING.value, F.ROLLED_BACK.value, F.SKIPPED_IDENTICAL.value, F.CONFLICT.value, F.SOURCE_CHANGED.value):
            self._remove_own_part(job_id, rec, rep)
            return "done"
        if rec["preserved_state"] == "removed" or (rec["preserved_state"] == "removing" and
                                                   _ident(rec["preserved_path"]) != _jl(rec["old_identity"])):
            rep["left_untouched"].append(dict(path=rec["committed_path"], reason="previous version already finalized; the "
                                                                                 "committed file is the only copy and was kept"))
            return "unsafe"
        if st == F.REMOVING_SOURCE.value:
            jn.transition_file(job_id, seq, F.COMMITTED, intent=None)
            rec, st = self._rec(job_id, seq), F.COMMITTED.value
        if st != F.ROLLING_BACK.value:
            target = rec["committed_path"] or _intent(rec).get("target") or rec["dst"]
            jn.transition_file(job_id, seq, F.ROLLING_BACK, intent=json.dumps({"step": "undo", "from": st, "target": target}))
        crash("undo.after_intent")
        rec = self._rec(job_id, seq)
        it = _intent(rec)
        target, origin = it.get("target") or rec["dst"], it.get("from")
        old = _jl(rec["old_identity"])
        # 1. a published file of this job (only states that can have published)
        r1 = "n/a"
        if origin in PUBLISH_STATES:
            di = _ident(target)
            published = _jl(rec["dst_identity"]) or _jl(rec["part_identity"])
            if di is None:
                r1 = "absent"
            elif old is not None and di == old and target == rec["dst"]:
                r1 = "old_in_place"                            # never moved aside, nothing published
            else:
                r1 = CP.remove_if_identity(target, published, policy=self.policy, expect_sha256=rec["src_sha256"])
        crash("undo.after_remove")
        # 2. the moved-aside previous version
        r2 = "n/a"
        if rec["preserved_path"] and rec["preserved_state"] in ("planned", "moved", "removing"):
            if old is not None and _ident(rec["dst"]) == old:
                r2 = "already_restored"                        # (or never moved) - a file at the preserved name is not ours
            else:
                r2 = CP.restore_preserved(rec["preserved_path"], rec["dst"], old, policy=self.policy)
        crash("undo.after_restore")
        # 3. this job's own .part
        self._remove_own_part(job_id, rec, rep)
        if r2 in ("occupied", "mismatch") or (r2 == "absent" and rec["preserved_state"] == "moved"):
            rep["left_untouched"].append(dict(path=rec["preserved_path"], reason=f"previous version could not be restored ({r2})"))
            return "unsafe"
        if r1 == "mismatch":
            jn.transition_file(job_id, seq, F.CONFLICT, intent=None, error="destination changed by someone else; left in place")
            rep["left_untouched"].append(dict(path=target, reason="destination is not the file this job wrote; left in place"))
            return "kept"
        jn.transition_file(job_id, seq, F.ROLLED_BACK, intent=None, error="rolled back",
                           preserved_state="restored" if r2 in ("restored", "already_restored") else rec["preserved_state"])
        return "done"

    def _remove_created_dirs(self, job_id):
        for d in sorted(json.loads(self.journal.get_job(job_id)["created_dirs"] or "[]"), key=len, reverse=True):
            try:
                os.rmdir(d)                              # only folders this job created, only if empty
            except OSError:
                pass

    # ================================================================================================= recovery
    def detect_interrupted(self) -> List[str]:
        """mark jobs whose owner is provably dead (their job lock is free) INTERRUPTED. Nothing on disk changes."""
        out = []
        for job in self.journal.list_jobs(ACTIVE_JOB_STATES, limit=100000):
            if self.locks.probe(job_key(job["job_id"])):
                try:
                    self.journal.transition_job(job["job_id"], J.INTERRUPTED, expected=[job["state"]],
                                                detail={"reason": "owner process gone", "was": job["state"]})
                    if job.get("control"):                     # audit: a pause request never outlives its owner
                        self.journal.set_job(job["job_id"], control=None)
                    out.append(job["job_id"])
                except Exception:
                    pass
        return out

    def _unavailable(self, job, files) -> List[str]:
        out = []
        for root in (self.base, self.vault):
            if root and any(f["dst"].startswith(root.rstrip("/") + "/") or f["src"].startswith(root.rstrip("/") + "/") for f in files) \
                    and not os.path.isdir(root):
                out.append(f"{root} is not available (volume not mounted?)")
        return sorted(set(out))

    def _src_status(self, rec) -> str:
        if not os.path.lexists(rec["src"]):
            return "missing"
        if os.path.islink(rec["src"]) or not os.path.isfile(rec["src"]):
            return "changed"
        if rec["src_identity"] and (_ident(rec["src"]) != _jl(rec["src_identity"]) or _sha(rec["src"]) != rec["src_sha256"]):
            return "changed"
        return "ok"

    def _classify(self, job, rec) -> Dict[str, Any]:
        """deterministic per-file classification; every claim checked by identity AND hash"""
        st = rec["state"]
        out = dict(seq=rec["seq"], rel=rec["rel_path"], state=st, cls=None, ambiguous=None, notes=[])
        own = self._own_part(rec)
        if own == "unrecognized":
            out["notes"].append(f"unrecognized temporary file left untouched: {rec['part_path']}")
        if st == F.SKIPPED_IDENTICAL.value:
            out["cls"] = "skipped"
        elif st == F.CONFLICT.value:
            out.update(cls="conflict", ambiguous="destination_conflict")
        elif st == F.ROLLING_BACK.value:
            out["cls"] = "undo_pending"
        elif st in (F.PENDING.value, F.FAILED.value, F.ROLLED_BACK.value, F.SOURCE_CHANGED.value, F.COPYING.value,
                    F.STAGED.value, F.VERIFIED.value):
            s = "changed" if st == F.SOURCE_CHANGED.value else self._src_status(rec)
            if s != "ok":
                out.update(cls="needs_copy", ambiguous=f"source_{s}")
            elif st == F.VERIFIED.value and own == "own" and _sha(rec["part_path"]) == rec["part_sha256"] == rec["src_sha256"]:
                out["cls"] = "staged_ok"
            else:
                out["cls"] = "needs_copy"
        elif st == F.COMMITTING.value:
            target = _intent(rec).get("target") or rec["dst"]
            di, old = _ident(target), _jl(rec["old_identity"])
            out["target"] = target
            if di is not None and di == _jl(rec["part_identity"]):
                out["cls"] = "published_unrecorded"
                if _sha(target) != rec["src_sha256"]:
                    out["ambiguous"] = "destination_changed"
                elif rec["preserved_path"] and _ident(rec["preserved_path"]) != old:
                    out["ambiguous"] = "preserved_missing" if not os.path.lexists(rec["preserved_path"]) else "preserved_changed"
            elif own == "own" and _sha(rec["part_path"]) == rec["src_sha256"]:
                s = self._src_status(rec)
                if rec["preserved_path"] and di is None and _ident(rec["preserved_path"]) == old:
                    out["cls"] = "preserved_aside"
                elif (di is None) or (old is not None and di == old):
                    out["cls"] = "staged_ok"
                else:
                    out.update(cls="staged_ok", ambiguous="destination_changed")
                if s != "ok" and not out["ambiguous"]:
                    out["ambiguous"] = f"source_{s}"
            else:
                out.update(cls="unknown", ambiguous="part_missing")
        elif st in (F.COMMITTED.value, F.REMOVING_SOURCE.value, F.SOURCE_REMOVED.value):
            target = rec["committed_path"]
            di = _ident(target)
            out["cls"] = "published_ok"
            if di is None:
                out["ambiguous"] = "destination_missing"
            elif di != _jl(rec["dst_identity"]) or _sha(target) != rec["src_sha256"]:
                out["ambiguous"] = "destination_changed"
            if rec["preserved_path"] and rec["preserved_state"] in ("moved", "removing"):
                pi = _ident(rec["preserved_path"])
                if pi is None and rec["preserved_state"] == "moved":
                    out["ambiguous"] = out["ambiguous"] or "preserved_missing"
                elif pi is not None and pi != _jl(rec["old_identity"]):
                    out["ambiguous"] = out["ambiguous"] or "preserved_changed"
            out["source_removed"] = st == F.SOURCE_REMOVED.value or (st == F.REMOVING_SOURCE.value and not os.path.lexists(rec["src"]))
        else:
            out.update(cls="unknown", ambiguous="unknown_state")
        return out

    def assess(self, job_id: str) -> Dict[str, Any]:
        """read-only recovery assessment"""
        job = self.journal.get_job(job_id)
        if job is None:
            raise TransferRefused(f"unknown job {job_id}")
        files = self.journal.get_files(job_id)
        unavailable = self._unavailable(job, files)
        cls = [] if unavailable else [self._classify(job, r) for r in files]
        amb = [dict(seq=c["seq"], rel=c["rel"], reason=c["ambiguous"]) for c in cls if c["ambiguous"]]
        terminal = JobState(job["state"]) in TERMINAL_JOB_STATES
        return dict(job_id=job_id, state=job["state"], decision=job["recovery_decision"], unavailable=unavailable,
                    files=cls, ambiguous=amb, notes=[n for c in cls for n in c["notes"]], terminal=terminal,
                    resumable=not terminal and not unavailable and not amb, discardable=not terminal and not unavailable)

    def _recovery(self, job_id, decision, lock_timeout, fn):
        job = self.journal.get_job(job_id)
        if job is None:
            raise TransferRefused(f"unknown job {job_id}")
        if JobState(job["state"]) in TERMINAL_JOB_STATES:
            return dict(job_id=job_id, noop=True, state=job["state"],
                        ok=(job["state"] == J.CANCELLED.value) == (decision == "discard"))
        if job["recovery_decision"] and job["recovery_decision"] != decision:
            raise TransferRefused(f"job {job_id} is being recovered with '{job['recovery_decision']}'; it cannot be "
                                  f"switched to '{decision}'")
        try:
            with self.locks.hold([job_key(job_id)], timeout=lock_timeout):
                with self.locks.hold(self._keys(job, self.journal.get_files(job_id)), timeout=lock_timeout):
                    return fn(job_id)
        except LockTimeout as e:
            raise TransferRefused(f"job {job_id} is in use: {e}")

    def resume(self, job_id: str, *, lock_timeout: float = 30.0, chunk_size: int = CP.CHUNK) -> Dict[str, Any]:
        return self._recovery(job_id, "resume", lock_timeout, lambda j: self._resume_locked(j, chunk_size))

    def discard(self, job_id: str, *, lock_timeout: float = 30.0) -> Dict[str, Any]:
        return self._recovery(job_id, "discard", lock_timeout, self._discard_locked)

    def _resume_locked(self, job_id, chunk_size):
        jn = self.journal
        job = jn.get_job(job_id)
        if job["state"] not in (J.INTERRUPTED.value, J.PAUSED.value, J.NEEDS_ATTENTION.value):
            raise TransferRefused(f"job {job_id} is {job['state']}; only interrupted or paused jobs (or needs-attention jobs "
                                  f"after a human resolved the cause) can be resumed")
        a = self.assess(job_id)
        if not a["resumable"]:
            raise TransferRefused(f"job {job_id} cannot be resumed safely: " +
                                  "; ".join(a["unavailable"] + [f"{x['rel']}: {x['reason']}" for x in a["ambiguous"]]))
        op, mode = Operation(job["operation"]), CommitMode(job["commit_mode"])
        spec = json.loads(job["spec_json"])
        if job["study_id"] and op in PIPELINE_GUARDED_OPS and study_processing_active(self.base, job["study_id"]):
            raise TransferRefused(f"study {job['study_id']} is being processed by the pipeline")
        jn.set_job(job_id, recovery_decision="resume", recovery_attempts=int(job["recovery_attempts"] or 0) + 1,
                   control=None)                            # audit: a stale pause request of a previous run is dropped
        jn.transition_job(job_id, J.RECOVERING, owner_pid=os.getpid(), detail={"decision": "resume"})
        crash("recover.after_decision")
        rep = self._report(job_id)
        cls = {c["seq"]: c for c in a["files"]}
        fresh: List[int] = []
        try:
            # 1. a rollback that a crash left half done is finished first; those files are then staged again
            for rec in jn.get_files(job_id):
                if cls[rec["seq"]]["cls"] == "undo_pending":
                    if self._undo_file(job_id, rec, rep) != "done":
                        raise CP.CopyError(f"{rec['rel_path']}: the earlier rollback cannot be completed safely")
                    cls[rec["seq"]]["cls"] = "needs_copy"
            # 2. publishes that happened but were not recorded (identity + hash verified by assess)
            for rec in jn.get_files(job_id):
                c = cls[rec["seq"]]
                if c["cls"] == "published_unrecorded":
                    jn.transition_file(job_id, rec["seq"], F.COMMITTED, committed_path=c["target"], dst_identity=rec["part_identity"],
                                       dst_sha256=rec["src_sha256"], intent=None,
                                       preserved_state="moved" if rec["preserved_path"] else "none")
                elif c["cls"] == "staged_ok" and rec["state"] == F.COMMITTING.value:
                    # intent recorded, no rename happened: back to VERIFIED (the part is re-verified, the old file in place)
                    jn.transition_file(job_id, rec["seq"], F.VERIFIED, intent=None, preserved_path=None, old_identity=None,
                                       preserved_state="none")
            # 3. stage everything that is not staged - all verified before anything new is committed
            for rec in jn.get_files(job_id):
                if cls[rec["seq"]]["cls"] != "needs_copy":
                    continue
                self._checkpoint(job_id, "resume_before_stage")
                self._remove_own_part(job_id, rec, rep)
                if rec["state"] != F.PENDING.value:
                    jn.transition_file(job_id, rec["seq"], F.PENDING, intent=None)
                jn.update_file(job_id, rec["seq"], attempt=int(rec["attempt"] or 0) + 1)
                r = self._stage_one(job_id, self._rec(job_id, rec["seq"]), mode, chunk_size,
                                    control=self._chunk_control(job_id))
                crash("recover.after_stage")
                if isinstance(r, CP.CopyResult):
                    if r.status != "skipped_identical":
                        raise CP.CopyError(f"{r.dst} exists with different content; nothing was overwritten")
                    continue
                fresh.append(rec["seq"])
            # 4. commit every verified file; publish moved-aside cases
            for rec in jn.get_files(job_id):
                c = cls[rec["seq"]]
                if rec["state"] in (F.VERIFIED.value, F.COMMITTING.value):
                    self._checkpoint(job_id, "resume_before_commit")
                if rec["state"] == F.VERIFIED.value:
                    self._commit_one(job_id, rec, self._staged_from(job_id, rec), mode, rep)
                elif rec["state"] == F.COMMITTING.value and c["cls"] == "preserved_aside":
                    if _ident(rec["part_path"]) != _jl(rec["part_identity"]) or _sha(rec["part_path"]) != rec["src_sha256"]:
                        raise CP.IntegrityError(f"{rec['part_path']} changed; not published")
                    if self._src_status(rec) != "ok":
                        raise CP.SourceChanged(f"{rec['src']} changed; not published")
                    CP._rename_exclusive(rec["part_path"], c["target"])
                    crash("commit.after_publish")
                    jn.transition_file(job_id, rec["seq"], F.COMMITTED, committed_path=c["target"], dst_identity=rec["part_identity"],
                                       dst_sha256=rec["src_sha256"], preserved_state="moved", intent=None)
            final = J.COMPLETED
            if op == Operation.MOVE:
                self._checkpoint(job_id, "resume_before_remove_sources")
                final = self._remove_sources(job_id, spec, rep)
            self._checkpoint(job_id, "resume_before_finalize")
            self._finalize(job_id, spec, rep)
        except _PAUSE_EXC as e:
            # paused at a safe boundary during the resume: the 'resume' decision stays recorded; a partial .part of
            # the file being copied is kept (its identity is journaled) and is re-staged by the next resume
            return self._pause(job_id, rep, getattr(e, "where", "resume_during_copy"))
        except BaseException as e:
            # a non-ambiguous failure while resuming: everything done so far is recorded; the job is safe to retry
            for seq in fresh:
                rec = self._rec(job_id, seq)
                if rec["state"] == F.VERIFIED.value:
                    self._remove_own_part(job_id, rec, rep)
                    jn.transition_file(job_id, seq, F.FAILED, error=f"resume failed: {e}")
            rep["errors"].append(f"{type(e).__name__}: {e}")
            jn.transition_job(job_id, J.INTERRUPTED, error=f"resume failed: {type(e).__name__}: {e}")
            rep.update(state=J.INTERRUPTED.value, ok=False)
            return rep
        rep["committed"] = [r["committed_path"] for r in jn.get_files(job_id) if r["state"] in (F.COMMITTED.value, F.SOURCE_REMOVED.value)]
        jn.transition_job(job_id, final, detail={"recovered": "resume"})
        rep.update(state=final.value, ok=True)
        return rep

    def _discard_locked(self, job_id):
        jn = self.journal
        job = jn.get_job(job_id)
        if job["state"] not in (J.INTERRUPTED.value, J.PAUSED.value, J.NEEDS_ATTENTION.value, J.FAILED.value):
            raise TransferRefused(f"job {job_id} is {job['state']}; only interrupted / paused / failed / needs-attention jobs "
                                  f"can be discarded")
        a = self.assess(job_id)
        if a["unavailable"]:
            raise TransferRefused(f"job {job_id} cannot be discarded now: " + "; ".join(a["unavailable"]))
        jn.set_job(job_id, recovery_decision="discard", recovery_attempts=int(job["recovery_attempts"] or 0) + 1,
                   control=None)
        jn.transition_job(job_id, J.RECOVERING, owner_pid=os.getpid(), detail={"decision": "discard"})
        crash("recover.after_decision")
        rep = self._report(job_id)
        unsafe = False
        try:
            for rec in reversed(jn.get_files(job_id)):
                unsafe |= self._undo_file(job_id, rec, rep) == "unsafe"
            self._remove_created_dirs(job_id)
        except BaseException as e:
            rep["errors"].append(f"{type(e).__name__}: {e}")
            jn.transition_job(job_id, J.INTERRUPTED, error=f"discard failed: {type(e).__name__}: {e}")
            rep.update(state=J.INTERRUPTED.value, ok=False)
            return rep
        final = J.NEEDS_ATTENTION if unsafe else J.CANCELLED
        jn.transition_job(job_id, final, detail={"recovered": "discard", "left_untouched": len(rep["left_untouched"]),
                                                 "kept_only_copy": len(rep["kept_only_copy"])})
        rep.update(state=final.value, ok=not unsafe)
        return rep
