"""uengine/transfer/service.py - Phase 1b: journal-backed transfer jobs built on the verified copier.

TransferService(project, vault).transfer(operation, items, study_id=None, mode=None) plans, records and runs one job:

  submit   every item (src -> dst) is planned with tree.plan_tree (links never followed, Finder metadata and transfer
           artifacts skipped and reported); every source and destination passes the Phase 0 PathPolicy; a move source
           must be removable; destinations on filesystems without an exclusive commit (exFAT) are refused; duplicate
           destinations refused. The job and its complete file list are written to the journal (state queued).
  run      PREPARING  locks (study + every destination), refuse if the study's pipeline run is active,
                      NEVER_OVERWRITE: every existing destination is compared first - any conflict -> NEEDS_ATTENTION
                      with NOTHING written
           PHASE A    every file is staged into a job-owned .part, flushed, read back uncached and verified.
                      No destination is touched. Any failure -> all of this job's .part files removed -> FAILED.
           PHASE B    COMMITTING: empty folders created, every verified file published with an exclusive commit.
                      Any failure -> every commit of this job is rolled back (only files that are still exactly what
                      this job wrote; moved-aside previous versions return) -> FAILED (rolled back), or NEEDS_ATTENTION
                      if a rollback step was itself unsafe (the journal lists exactly what is where).
           PHASE C    move only: REMOVING_SOURCES - a source file is removed only if it is unchanged since it was
                      hashed and its committed copy is still in place; links, metadata, unreadable and changed files stay
                      (COMPLETED_WITH_RETAINED_SOURCES); folders are removed only when empty and removable by policy.
           FINALIZE   previous versions moved aside by REPLACE / PRESERVE are removed only now (whole job verified),
                      unless keep_previous=True.
Execution is synchronous in 1b. Background workers, pause / resume, interrupted-job recovery and the HTTP job API are
milestones 1c-1e; a job interrupted by a crash stays non-terminal in the journal for 1c recovery.
"""
import os
import secrets
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import copier as CP
from .journal import TransferJournal
from .locks import LockTimeout, TransferLocks, dst_key, study_key, study_processing_active
from .models import DEFAULT_COMMIT_MODE, CommitMode, FileState, JobState, Operation
from .tree import plan_tree
from ..safety import PathPolicy, SafetyError, canon, validate_study_code

F, J = FileState, JobState
PIPELINE_GUARDED_OPS = {Operation.ARCHIVE, Operation.SYNC, Operation.STAGE}


class TransferRefused(RuntimeError):
    """the job was refused before anything was recorded or written"""


def _job_id(op: Operation, study: Optional[str]) -> str:
    return f"{op.value}-{study or 'x'}-{time.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"[:64]


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
               mode: Optional[CommitMode] = None, keep_previous: bool = False) -> str:
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
            except CP.ExclusiveCommitUnsupported as e:
                raise TransferRefused(str(e))
        job_id = _job_id(op, study_id)
        self.journal.create_job(job_id, op.value, mode.value, files, study_id=study_id,
                                spec=dict(roots=roots, empty_dirs=empty_dirs, skipped=skipped, keep_previous=bool(keep_previous)))
        return job_id

    def transfer(self, operation, items, study_id=None, mode=None, keep_previous=False, **run_kw) -> Dict[str, Any]:
        return self.run(self.submit(operation, items, study_id=study_id, mode=mode, keep_previous=keep_previous), **run_kw)

    # ================================================================================================= run
    def run(self, job_id: str, *, lock_timeout: float = 30.0, chunk_size: int = CP.CHUNK, _hooks: Optional[dict] = None) -> Dict[str, Any]:
        hooks = _hooks or {}
        job = self.journal.get_job(job_id)
        if job is None:
            raise TransferRefused(f"unknown job {job_id}")
        import json as _json
        spec = _json.loads(job["spec_json"])
        op, mode = Operation(job["operation"]), CommitMode(job["commit_mode"])
        rep = dict(job_id=job_id, operation=op.value, commit_mode=mode.value, study_id=job["study_id"], committed=[],
                   skipped_identical=[], conflicts=[], skipped=spec.get("skipped", []), retained_sources=[],
                   preserved_kept=[], errors=[], state=None)
        self.journal.transition_job(job_id, J.PREPARING, expected=[J.QUEUED], owner_pid=os.getpid())
        files = self.journal.get_files(job_id)
        keys = [dst_key(f["dst"]) for f in files] + [dst_key(d) for d in spec.get("empty_dirs", [])]
        if job["study_id"]:
            keys.append(study_key(job["study_id"]))
        try:
            with self.locks.hold(keys, timeout=lock_timeout):
                return self._run_locked(job_id, op, mode, spec, files, rep, chunk_size, hooks)
        except LockTimeout as e:
            return self._end(job_id, J.FAILED, rep, f"busy: {e}")

    def _end(self, job_id, state, rep, error=None):
        if error:
            rep["errors"].append(error)
        self.journal.transition_job(job_id, state, error=error, detail={k: len(v) for k, v in rep.items() if isinstance(v, list)})
        rep["state"] = JobState(state).value
        rep["ok"] = state in (J.COMPLETED, J.COMPLETED_WITH_RETAINED_SOURCES)
        return rep

    def _run_locked(self, job_id, op, mode, spec, files, rep, chunk_size, hooks):
        jn, pol = self.journal, self.policy
        if job_study := self.journal.get_job(job_id)["study_id"]:
            if op in PIPELINE_GUARDED_OPS and study_processing_active(self.base, job_study):
                return self._end(job_id, J.FAILED, rep, f"study {job_study} is being processed by the pipeline; "
                                                        f"{op.value} refused until the run has finished")
        # ---------------------------------------------------------------- pre-check existing destinations
        todo = []
        for f in files:
            if os.path.lexists(f["dst"]) and mode == CommitMode.NEVER_OVERWRITE:
                if not os.path.isfile(f["dst"]) or os.path.islink(f["dst"]):
                    rep["conflicts"].append(dict(rel=f["rel_path"], dst=f["dst"], reason="destination is not a regular file"))
                    jn.transition_file(job_id, f["seq"], F.CONFLICT, error="destination is not a regular file")
                    continue
                s, _ = CP._hash_file(f["src"])
                d, _ = CP._hash_file(f["dst"])
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
        # ---------------------------------------------------------------- phase A: stage + verify everything
        staged: List[Tuple[dict, CP.StagedFile]] = []
        made_dirs: List[str] = []                       # folders THIS job created (removed again if the job fails)
        done_bytes = 0
        try:
            if todo:
                jn.transition_job(job_id, J.COPYING)
            for f in todo:
                jn.transition_file(job_id, f["seq"], F.COPYING, part_path=f"{f['dst']}.part-{job_id}")
                jn.update_progress(job_id, current_file=f["rel_path"])
                made_dirs += self._makedirs(os.path.dirname(f["dst"]))
                if hooks.get("before_stage"):
                    hooks["before_stage"](f)
                state = {"phase": "copying"}

                def progress(phase, n, _st=state):
                    if phase != _st["phase"]:
                        nxt = {"flushing": J.FLUSHING, "verifying": J.VERIFYING}.get(phase)
                        if nxt:
                            jn.transition_job(job_id, nxt)
                        _st["phase"] = phase
                r = CP.stage_file(f["src"], f["dst"], policy=pol, job_tag=job_id, mode=mode, chunk_size=chunk_size, progress=progress)
                if isinstance(r, CP.CopyResult):          # destination appeared identical / conflicting meanwhile
                    if r.status == "skipped_identical":
                        jn.transition_file(job_id, f["seq"], F.SKIPPED_IDENTICAL, src_sha256=r.src_sha256, dst_sha256=r.dst_sha256)
                        rep["skipped_identical"].append(r.dst)
                        continue                              # nothing was copied for this file
                    else:
                        jn.transition_file(job_id, f["seq"], F.CONFLICT, src_sha256=r.src_sha256, dst_sha256=r.dst_sha256)
                        rep["conflicts"].append(dict(rel=f["rel_path"], dst=r.dst))
                        raise CP.CopyError(f"{r.dst} appeared with different content during the job")
                else:
                    jn.transition_file(job_id, f["seq"], F.STAGED, src_sha256=r.src_sha256)
                    jn.transition_file(job_id, f["seq"], F.VERIFIED, part_sha256=r.part_sha256)
                    staged.append((f, r))
                    done_bytes += r.size
                    jn.update_progress(job_id, phase_bytes=done_bytes)
                if state["phase"] == "verifying":
                    jn.transition_job(job_id, J.COPYING)
        except BaseException as e:
            for f, s in staged:
                try:
                    CP.discard_staged(s)
                    jn.transition_file(job_id, f["seq"], F.ROLLED_BACK, error="discarded: job failed before commit")
                except Exception as e2:
                    rep["errors"].append(f"could not discard {s.part}: {e2}")
            self._remove_made_dirs(made_dirs)
            self._fail_open_files(job_id, e)
            state = J.NEEDS_ATTENTION if rep["conflicts"] else J.FAILED
            return self._end(job_id, state, rep, f"{type(e).__name__}: {e} - no destination was changed")
        # ---------------------------------------------------------------- phase B: commit everything (or nothing)
        jn.transition_job(job_id, J.COMMITTING)
        committed: List[Tuple[dict, CP.CopyResult]] = []
        try:
            for d in sorted(set(spec.get("empty_dirs", [])) | {os.path.dirname(s.dst) for _, s in staged}):
                made_dirs += self._makedirs(d)
            for i, (f, s) in enumerate(staged):
                if hooks.get("before_commit"):
                    hooks["before_commit"](i, f)
                r = CP.commit_staged(s, mode, policy=pol)
                if r.status != "committed":
                    rep["conflicts"].append(dict(rel=f["rel_path"], dst=r.dst, reason=f"{r.status} at commit time"))
                    if r.status == "skipped_identical":
                        jn.transition_file(job_id, f["seq"], F.SKIPPED_IDENTICAL, dst_sha256=r.dst_sha256)
                        rep["conflicts"].pop()
                        rep["skipped_identical"].append(r.dst)
                        continue
                    jn.transition_file(job_id, f["seq"], F.CONFLICT, error="destination created by someone else during commit")
                    raise CP.CopyError(f"{r.dst} was created by someone else during the commit; nothing was overwritten")
                jn.transition_file(job_id, f["seq"], F.COMMITTED, dst_sha256=r.dst_sha256, committed_path=r.dst,
                                   preserved_path=r.preserved_path)
                committed.append((f, r))
                jn.update_progress(job_id, done_files=len(committed), done_bytes=sum(x.size for _, x in committed))
        except BaseException as e:
            unsafe = self._rollback(job_id, committed, staged[len(committed):], made_dirs, rep)
            self._fail_open_files(job_id, e)
            if unsafe or rep["conflicts"]:
                return self._end(job_id, J.NEEDS_ATTENTION, rep, f"{type(e).__name__}: {e}; rollback "
                                                                f"{'INCOMPLETE - see the job report' if unsafe else 'complete'}")
            return self._end(job_id, J.FAILED, rep, f"{type(e).__name__}: {e} - all commits of this job were rolled back")
        rep["committed"] = [r.dst for _, r in committed]
        rep["created_dirs"] = made_dirs
        # ---------------------------------------------------------------- phase C: move - remove verified sources
        final = J.COMPLETED
        if op == Operation.MOVE:
            jn.transition_job(job_id, J.REMOVING_SOURCES)
            if hooks.get("before_remove_sources"):
                hooks["before_remove_sources"]()
            final = self._remove_sources(job_id, committed, spec, rep)
        # ---------------------------------------------------------------- finalize previous versions
        for f, r in committed:
            if r.preserved_path:
                if spec.get("keep_previous"):
                    rep["preserved_kept"].append(r.preserved_path)
                else:
                    try:
                        CP.finalize_preserved(r, policy=pol)
                    except Exception as e:
                        rep["preserved_kept"].append(r.preserved_path)
                        rep["errors"].append(f"previous version kept at {r.preserved_path}: {e}")
        return self._end(job_id, final, rep)

    # ================================================================================================= helpers
    def _makedirs(self, d: str) -> List[str]:
        """create d (and missing parents) through the policy; returns the folders this call created"""
        made = []
        p = d
        missing = []
        while p and not os.path.isdir(p):
            missing.append(p)
            p = os.path.dirname(p)
        for m in reversed(missing):
            self.policy.check_write_target(m)
            try:
                os.mkdir(m)
                made.append(m)
            except FileExistsError:
                if not os.path.isdir(m):
                    raise
        return made

    def _fail_open_files(self, job_id, exc):
        for f in self.journal.get_files(job_id, [F.PENDING, F.COPYING, F.STAGED]):
            try:
                self.journal.transition_file(job_id, f["seq"], F.FAILED, error=f"{type(exc).__name__}: {exc}")
            except Exception:
                pass

    def _rollback(self, job_id, committed, uncommitted, made_dirs, rep) -> bool:
        """undo this job's commits in reverse; returns True if any step could not be done safely"""
        unsafe = False
        for f, r in reversed(committed):
            try:
                CP.rollback_committed(r, policy=self.policy)
                self.journal.transition_file(job_id, f["seq"], F.ROLLED_BACK, error="rolled back: a later commit failed")
            except Exception as e:
                unsafe = True
                rep["errors"].append(f"rollback of {r.dst} not done: {e}")
        for f, s in uncommitted:
            try:
                CP.discard_staged(s)
                self.journal.transition_file(job_id, f["seq"], F.ROLLED_BACK, error="discarded: job rolled back")
            except Exception as e:
                rep["errors"].append(f"could not discard {s.part}: {e}")
        self._remove_made_dirs(made_dirs)
        return unsafe

    @staticmethod
    def _remove_made_dirs(made_dirs):
        for d in sorted(set(made_dirs), key=len, reverse=True):
            try:
                os.rmdir(d)                                  # only folders this job created, only if empty
            except OSError:
                pass

    def _remove_sources(self, job_id, committed, spec, rep):
        retained = False
        for f, r in committed:
            src = r.src
            if not os.path.lexists(src):
                continue
            # the source is removed only if it still hashes to what was copied AND the committed copy is still ours
            rec = self.journal.get_files(job_id)[f["seq"]]
            ok = (not os.path.islink(src) and rec["src_sha256"] == r.src_sha256 and CP._same(r.dst, r.dst_identity))
            if ok:
                h, _ = CP._hash_file(src)
                ok = h == r.src_sha256
            if ok:
                try:
                    self.policy.check_modify(src)
                    os.remove(src)
                    self.journal.transition_file(job_id, f["seq"], F.SOURCE_REMOVED)
                    continue
                except (SafetyError, OSError) as e:
                    rep["errors"].append(f"source kept {src}: {e}")
            retained = True
            rep["retained_sources"].append(src)
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
