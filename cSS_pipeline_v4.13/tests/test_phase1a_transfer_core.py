"""Phase 1 milestone 1a tests: state machines (models), persistent journal, verified single-file copier.

Isolated (tests/_isolation.py), synthetic files in temporary directories only. A synthetic protected tree (original MRI,
reader calls, call ledger, labels, model store, Pensieve, Vault originals) is fingerprinted before the suite and must
be byte-identical after it; every attempt to write into it must be refused by the Phase 0 policy."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from uengine.safety import PathPolicy                                  # noqa: E402
from uengine.transfer import copier as CP                              # noqa: E402
from uengine.transfer import journal as JN                             # noqa: E402
from uengine.transfer.models import (CommitMode, FileState, JobState, TransitionError, JOB_TRANSITIONS,  # noqa: E402
                                     FILE_TRANSITIONS, TERMINAL_JOB_STATES, check_job_transition, check_file_transition)


def _w(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return p


def _sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _tree_fingerprint(root):
    out = {}
    for r, ds, fs in os.walk(root):
        for f in fs:
            p = os.path.join(r, f)
            st = os.lstat(p)
            out[os.path.relpath(p, root)] = (st.st_size, st.st_mtime_ns, _sha(p))
        for d in ds:
            out[os.path.relpath(os.path.join(r, d), root) + "/"] = "dir"
    return out


PROTECTED = {
    "raw/M01/SWI/swi.nii": b"RAW", "data/M01_swi.nii": b"DATA", "app_data/import_src/S16/a.dcm": b"IMPORT",
    "review/M01_calls_alice.csv": b"cand_id,call\n1,cSS\n", "review/M01_missed.csv": b"m", "review/M01_final.json": b"{}",
    "review/call_policy.json": b"{}", "labels/candidate_labels.csv": b"l", "percival/registry/v1.json": b"{}",
    "app_data/pensieve.db": b"SQLITE", "app_data/settings.json": b"{}",
}
VAULT_PROTECTED = {"original_mri/M01/o.dcm": b"VORIG", "PENSIEVE/pensieve.db": b"VP", "manifest/vault_manifest.json": b"{}"}


class Env:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="p1a_")
        self.base = os.path.join(self.tmp, "proj")
        self.vault = os.path.join(self.tmp, "Volumes", "Percival", "PERCIVAL_VAULT")
        for rel, data in PROTECTED.items():
            _w(os.path.join(self.base, rel), data)
        for rel, data in VAULT_PROTECTED.items():
            _w(os.path.join(self.vault, rel), data)
        _w(os.path.join(self.tmp, "Volumes", "Percival", "Dicom", "M01", "c.dcm"), b"DICOM")
        os.makedirs(os.path.join(self.base, "work"), exist_ok=True)
        os.makedirs(os.path.join(self.vault, "studies"), exist_ok=True)
        self.policy = PathPolicy(self.base, self.vault)
        self.fp_base = self._prot_fp()

    def _prot_fp(self):
        fp = {}
        for rel in PROTECTED:
            p = os.path.join(self.base, rel)
            fp[p] = (_sha(p), os.stat(p).st_mtime_ns)
        for rel in VAULT_PROTECTED:
            p = os.path.join(self.vault, rel)
            fp[p] = (_sha(p), os.stat(p).st_mtime_ns)
        for d in ("raw", "data", "review", "labels", "percival", "app_data/import_src"):
            fp[os.path.join(self.base, d) + "/"] = sorted(os.listdir(os.path.join(self.base, d)))
        for d in ("original_mri", "PENSIEVE", "manifest"):
            fp[os.path.join(self.vault, d) + "/"] = sorted(os.listdir(os.path.join(self.vault, d)))
        return fp

    def assert_protected_intact(self, tc):
        tc.assertEqual(self._prot_fp(), self.fp_base, "protected scientific data or expert records changed")

    def work(self, rel, data):
        return _w(os.path.join(self.base, "work", rel), data)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ============================================================================================== models
class TestStateMachines(unittest.TestCase):
    def test_every_state_has_a_transition_entry(self):
        self.assertEqual(set(JOB_TRANSITIONS), set(JobState))
        self.assertEqual(set(FILE_TRANSITIONS), set(FileState))

    def test_terminal_states(self):
        self.assertEqual(TERMINAL_JOB_STATES, {JobState.COMPLETED, JobState.COMPLETED_WITH_RETAINED_SOURCES, JobState.CANCELLED})
        for t in TERMINAL_JOB_STATES:
            for s in JobState:
                with self.assertRaises(TransitionError):
                    check_job_transition(t, s)

    def test_legal_happy_path_and_illegal_shortcuts(self):
        path = [JobState.QUEUED, JobState.PREPARING, JobState.COPYING, JobState.FLUSHING, JobState.VERIFYING,
                JobState.COMMITTING, JobState.COPYING, JobState.FLUSHING, JobState.VERIFYING, JobState.COMMITTING,
                JobState.REMOVING_SOURCES, JobState.COMPLETED]
        for a, b in zip(path, path[1:]):
            check_job_transition(a, b)
        for a, b in [(JobState.QUEUED, JobState.COMPLETED), (JobState.COPYING, JobState.VERIFYING),
                     (JobState.FLUSHING, JobState.COMMITTING), (JobState.INTERRUPTED, JobState.COPYING),
                     (JobState.FAILED, JobState.COMPLETED), (JobState.PAUSED, JobState.COPYING)]:
            with self.subTest(a=a, b=b), self.assertRaises(TransitionError):
                check_job_transition(a, b)

    def test_interrupted_only_leaves_through_recovery(self):
        # 1c: an interrupted job is never re-run or cancelled directly - only a recorded resume / discard decision
        self.assertEqual(JOB_TRANSITIONS[JobState.INTERRUPTED], {JobState.RECOVERING})

    def test_file_states(self):
        for a, b in [(FileState.PENDING, FileState.COPYING), (FileState.COPYING, FileState.STAGED),
                     (FileState.STAGED, FileState.VERIFIED), (FileState.VERIFIED, FileState.COMMITTING),
                     (FileState.COMMITTING, FileState.COMMITTED), (FileState.COMMITTED, FileState.REMOVING_SOURCE),
                     (FileState.REMOVING_SOURCE, FileState.SOURCE_REMOVED)]:
            check_file_transition(a, b)
        for a, b in [(FileState.PENDING, FileState.COMMITTED), (FileState.STAGED, FileState.COMMITTED),
                     (FileState.COPYING, FileState.VERIFIED), (FileState.PENDING, FileState.SOURCE_REMOVED),
                     (FileState.VERIFIED, FileState.SOURCE_REMOVED), (FileState.COMMITTED, FileState.PENDING),
                     (FileState.VERIFIED, FileState.COMMITTED), (FileState.COMMITTED, FileState.SOURCE_REMOVED)]:
            with self.subTest(a=a, b=b), self.assertRaises(TransitionError):
                check_file_transition(a, b)


# ============================================================================================== journal
class TestJournal(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.j = JN.TransferJournal(self.E.base, self.E.vault)
        self.files = [dict(rel_path="a.nii", src="/s/a", dst="/d/a", size=10), dict(rel_path="b.nii", src="/s/b", dst="/d/b", size=20)]

    def tearDown(self):
        self.j.close()
        self.E.close()

    def test_location_and_durability_settings(self):
        self.assertEqual(self.j.path, os.path.join(self.E.base, "app_data", "transfers", "journal.db"))
        self.assertEqual(self.j.pragma("journal_mode"), "wal")
        self.assertEqual(self.j.pragma("synchronous"), 2)          # FULL
        self.assertEqual(self.j.pragma("foreign_keys"), 1)

    def test_create_and_read_back(self):
        self.j.create_job("job1", "archive", "never_overwrite", self.files, study_id="M01", spec={"k": 1})
        job = self.j.get_job("job1")
        self.assertEqual((job["state"], job["total_files"], job["total_bytes"]), ("queued", 2, 30))
        self.assertEqual([f["state"] for f in self.j.get_files("job1")], ["pending", "pending"])
        self.assertEqual(self.j.events("job1")[0]["kind"], "created")
        with self.assertRaises(JN.JournalError):
            self.j.create_job("job1", "archive", "never_overwrite", self.files)
        for bad in ("", "../x", "a/b", "."):
            with self.assertRaises(JN.JournalError):
                self.j.create_job(bad, "copy", "new_name", self.files)

    def test_illegal_or_stale_transition_changes_nothing(self):
        self.j.create_job("job1", "copy", "new_name", self.files)
        n_ev = len(self.j.events("job1"))
        with self.assertRaises(TransitionError):
            self.j.transition_job("job1", JobState.COMPLETED)
        with self.assertRaises(JN.StaleStateError):
            self.j.transition_job("job1", JobState.PREPARING, expected=[JobState.PAUSED])
        self.assertEqual(self.j.get_job("job1")["state"], "queued")
        self.assertEqual(len(self.j.events("job1")), n_ev)
        prev = self.j.transition_job("job1", JobState.PREPARING, expected=[JobState.QUEUED], owner_pid=os.getpid())
        self.assertEqual(prev, "queued")
        self.assertEqual(self.j.get_job("job1")["owner_pid"], os.getpid())
        ev = self.j.events("job1")[-1]
        self.assertEqual((ev["from_state"], ev["to_state"]), ("queued", "preparing"))

    def test_file_transitions_and_fields(self):
        self.j.create_job("job1", "copy", "new_name", self.files)
        self.j.transition_file("job1", 0, FileState.COPYING, part_path="/d/a.part-job1")
        with self.assertRaises(TransitionError):
            self.j.transition_file("job1", 0, FileState.COMMITTED)
        with self.assertRaises(JN.JournalError):
            self.j.transition_file("job1", 0, FileState.STAGED, not_a_field=1)
        self.j.transition_file("job1", 0, FileState.STAGED, src_sha256="ab" * 32)
        f0 = self.j.get_files("job1")[0]
        self.assertEqual((f0["state"], f0["part_path"], f0["src_sha256"]), ("staged", "/d/a.part-job1", "ab" * 32))
        self.assertEqual(len(self.j.get_files("job1", [FileState.PENDING])), 1)

    def test_progress_is_bounded_and_frozen_after_terminal(self):
        self.j.create_job("job1", "copy", "new_name", self.files)
        self.j.update_progress("job1", done_files=1, done_bytes=10, current_file="a.nii")
        with self.assertRaises(JN.JournalError):
            self.j.update_progress("job1", done_bytes=31)
        with self.assertRaises(JN.JournalError):
            self.j.update_progress("job1", done_files=-1)
        self.j.transition_job("job1", JobState.CANCELLED)
        with self.assertRaises(TransitionError):
            self.j.update_progress("job1", done_bytes=5)

    def test_persists_across_instances(self):
        self.j.create_job("job1", "stage", "preserve_previous", self.files, study_id="M01")
        self.j.transition_job("job1", JobState.PREPARING)
        self.j.transition_job("job1", JobState.COPYING)
        self.j.close()
        j2 = JN.TransferJournal(self.E.base, self.E.vault)
        try:
            self.assertEqual(j2.get_job("job1")["state"], "copying")
            self.assertEqual([r["job_id"] for r in j2.non_terminal_jobs()], ["job1"])
            self.assertEqual([e["to_state"] for e in j2.events("job1")], ["queued", "preparing", "copying"])
        finally:
            j2.close()
        self.j = JN.TransferJournal(self.E.base, self.E.vault)

    def test_refuses_newer_schema(self):
        self.j.close()
        con = sqlite3.connect(os.path.join(self.E.base, "app_data", "transfers", "journal.db"))
        con.execute("UPDATE schema_meta SET value='99' WHERE key='schema_version'")
        con.commit()
        con.close()
        with self.assertRaises(JN.JournalError):
            JN.TransferJournal(self.E.base, self.E.vault)
        con = sqlite3.connect(os.path.join(self.E.base, "app_data", "transfers", "journal.db"))
        con.execute("UPDATE schema_meta SET value='1' WHERE key='schema_version'")
        con.commit()
        con.close()
        self.j = JN.TransferJournal(self.E.base, self.E.vault)

    def test_concurrent_writers_are_serialised(self):
        files = [dict(rel_path=f"f{i}", src="/s", dst="/d", size=1) for i in range(400)]
        self.j.create_job("job1", "copy", "new_name", files)
        errors = []

        def worker(k):
            try:
                for i in range(100):
                    seq = k * 100 + i
                    self.j.transition_file("job1", seq, FileState.COPYING)
                    self.j.update_progress("job1", current_file=f"f{seq}")
            except Exception as e:  # pragma: no cover
                errors.append(e)
        ts = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errors, [])
        self.assertEqual(len(self.j.get_files("job1", [FileState.COPYING])), 400)

    def test_refuses_a_missing_project_folder(self):
        with self.assertRaises(JN.JournalError):
            JN.TransferJournal(os.path.join(self.E.tmp, "missing"))


# ============================================================================================== copier
class CopierBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.E = Env()

    @classmethod
    def tearDownClass(cls):
        cls.E.close()

    def tearDown(self):
        self.E.assert_protected_intact(self)
        stray = [os.path.join(r, f) for r, _, fs in os.walk(self.E.tmp) for f in fs if ".part-" in f]
        self.assertEqual(stray, [], "a .part file was left behind")

    def cp(self, src, dst, mode=CommitMode.REPLACE_AFTER_VERIFY, tag="j1", **kw):
        return CP.verified_copy(src, dst, policy=self.E.policy, job_tag=tag, mode=mode, **kw)

    def bad_readback(self):
        real = CP._hash_file
        return mock.patch.object(CP, "_hash_file", side_effect=lambda p, nocache=False, chunk=CP.CHUNK:
                                 ("0" * 64, nocache) if nocache else real(p, nocache, chunk))


class TestCopierIntegrity(CopierBase):
    def test_plain_copy_is_verified_uncached_and_directory_flushed(self):
        src = self.E.work("M01/a.nii", b"A" * 100000)
        dst = os.path.join(self.E.base, "work", "M02", "a.nii")
        calls = []
        real = CP._hash_file
        with mock.patch.object(CP, "_hash_file", side_effect=lambda p, nocache=False, chunk=CP.CHUNK:
                               calls.append((os.path.basename(p), nocache)) or real(p, nocache, chunk)):
            r = self.cp(src, dst, chunk_size=7777)
        self.assertEqual(r.status, "committed")
        self.assertEqual(r.src_sha256, _sha(src))
        self.assertEqual(r.dst_sha256, _sha(dst))
        self.assertEqual(_sha(dst), _sha(src))
        self.assertIn(("a.nii.part-j1", True), calls)               # read back from the staged file, uncached
        self.assertTrue(r.nocache_readback)
        self.assertTrue(r.dir_synced)
        self.assertIn(r.durability, ("F_FULLFSYNC", "os.fsync"))

    def test_readback_mismatch_keeps_existing_destination(self):
        src = self.E.work("M01/b.nii", b"NEW")
        dst = self.E.work("M02/b.nii", b"OLD-VALID")
        for mode in CommitMode:
            with self.subTest(mode=mode), self.bad_readback():
                if mode == CommitMode.NEVER_OVERWRITE:      # a different existing file is a conflict before any write
                    self.assertEqual(self.cp(src, dst, mode=mode).status, "conflict")
                else:
                    with self.assertRaises(CP.IntegrityError):
                        self.cp(src, dst, mode=mode)
            self.assertEqual(open(dst, "rb").read(), b"OLD-VALID")
            self.assertFalse(os.path.exists(dst + ".replaced-j1"))
        fresh = os.path.join(self.E.vault, "studies", "M01", "never_created.nii")
        for mode in CommitMode:                             # no destination yet: a bad read-back creates nothing
            with self.subTest(fresh_mode=mode), self.bad_readback():
                with self.assertRaises(CP.IntegrityError):
                    self.cp(src, fresh, mode=mode)
            self.assertFalse(os.path.exists(fresh))

    def test_flush_failure_fails_the_copy(self):
        src = self.E.work("M01/c.nii", b"NEW")
        dst = self.E.work("M02/c.nii", b"OLD")
        with mock.patch.object(CP, "flush_durability", return_value=(False, "flush_failed: EIO")):
            with self.assertRaises(CP.FlushFailed):
                self.cp(src, dst)
        self.assertEqual(open(dst, "rb").read(), b"OLD")

    def test_source_modified_during_copy(self):
        src = self.E.work("M01/d.nii", b"X" * 50000)
        dst = os.path.join(self.E.base, "work", "M02", "d.nii")

        def progress(phase, n):
            if phase == "copying" and n >= 10000 and not getattr(progress, "done", False):
                progress.done = True
                with open(src, "ab") as f:
                    f.write(b"tail")
                os.utime(src, ns=(os.stat(src).st_atime_ns, os.stat(src).st_mtime_ns + 1000))
        with self.assertRaises(CP.SourceChanged):
            self.cp(src, dst, chunk_size=10000, progress=progress)
        self.assertFalse(os.path.exists(dst))

    def test_source_rewritten_in_place_same_size(self):
        src = self.E.work("M01/e.nii", b"Y" * 40000)
        dst = os.path.join(self.E.base, "work", "M02", "e.nii")

        def before_commit():
            with open(src, "r+b") as f:
                f.write(b"Z")
            os.utime(src, ns=(os.stat(src).st_atime_ns, os.stat(src).st_mtime_ns + 5000))
        with self.assertRaises(CP.SourceChanged):
            self.cp(src, dst, _before_commit=None, chunk_size=40000, progress=lambda ph, n: before_commit() if ph == "verifying" else None)
        self.assertFalse(os.path.exists(dst))

    def test_edge_files(self):
        for rel, data in (("M01/zero.nii", b""), ("M01/.hidden_notes", b"h"), ("M01/ünïcødé ñame.nii.gz", b"u" * 3)):
            with self.subTest(rel=rel):
                src = self.E.work(rel, data)
                dst = os.path.join(self.E.base, "work", "EDGE", os.path.basename(rel))
                r = self.cp(src, dst)
                self.assertEqual(r.status, "committed")
                self.assertEqual(open(dst, "rb").read(), data)

    def test_large_multichunk_sparse_file(self):
        mb = int(os.environ.get("PERCIVAL_TEST_LARGE_MB", "96"))
        src = os.path.join(self.E.base, "work", "BIG", "big.nii")
        os.makedirs(os.path.dirname(src), exist_ok=True)
        with open(src, "wb") as f:
            f.truncate(mb * 1024 * 1024)
            f.seek(mb * 1024 * 1024 // 2)
            f.write(b"MIDDLE-MARKER")
        dst = os.path.join(self.E.base, "work", "BIG2", "big.nii")
        r = self.cp(src, dst)
        self.assertEqual(r.status, "committed")
        self.assertEqual(r.size, os.path.getsize(src))
        self.assertEqual(_sha(dst), _sha(src))
        os.remove(src)
        os.remove(dst)


class TestCommitModes(CopierBase):
    def test_identical_destination_is_skipped_in_every_mode(self):
        src = self.E.work("M01/same.nii", b"SAME")
        dst = self.E.work("M03/same.nii", b"SAME")
        mt = os.stat(dst).st_mtime_ns
        for mode in CommitMode:
            with self.subTest(mode=mode):
                r = self.cp(src, dst, mode=mode)
                self.assertEqual(r.status, "skipped_identical")
                self.assertEqual(os.stat(dst).st_mtime_ns, mt)

    def test_never_overwrite_reports_conflict_and_writes_nothing(self):
        src = self.E.work("M01/n.nii", b"NEW")
        dst = os.path.join(self.E.vault, "studies", "M01", "n.nii")
        _w(dst, b"ARCHIVED-DIFFERENT")
        r = self.cp(src, dst, mode=CommitMode.NEVER_OVERWRITE)
        self.assertEqual(r.status, "conflict")
        self.assertEqual(open(dst, "rb").read(), b"ARCHIVED-DIFFERENT")

    def test_never_overwrite_when_destination_appears_at_the_last_moment(self):
        src = self.E.work("M01/race.nii", b"MINE")
        dst = os.path.join(self.E.vault, "studies", "M01", "race.nii")
        r = self.cp(src, dst, mode=CommitMode.NEVER_OVERWRITE, _before_commit=lambda: _w(dst, b"SOMEONE-ELSE"))
        self.assertEqual(r.status, "conflict")
        self.assertEqual(open(dst, "rb").read(), b"SOMEONE-ELSE")
        r = self.cp(src, os.path.join(self.E.vault, "studies", "M01", "race2.nii"), mode=CommitMode.NEVER_OVERWRITE,
                    _before_commit=lambda: _w(os.path.join(self.E.vault, "studies", "M01", "race2.nii"), b"MINE"))
        self.assertEqual(r.status, "skipped_identical")

    def test_never_overwrite_new_file(self):
        src = self.E.work("M01/fresh.nii", b"FRESH")
        dst = os.path.join(self.E.vault, "studies", "M01", "fresh.nii")
        r = self.cp(src, dst, mode=CommitMode.NEVER_OVERWRITE)
        self.assertEqual(r.status, "committed")
        self.assertEqual(open(dst, "rb").read(), b"FRESH")

    def test_preserve_previous_keeps_the_old_version(self):
        src = self.E.work("M01/p.nii", b"NEW-STAGED")
        dst = self.E.work("M04/p.nii", b"OLD-LOCAL")
        r = self.cp(src, dst, mode=CommitMode.PRESERVE_PREVIOUS, tag="jobP")
        self.assertEqual(r.status, "committed")
        self.assertEqual(open(dst, "rb").read(), b"NEW-STAGED")
        self.assertEqual(r.preserved_path, dst + ".replaced-jobP")
        self.assertEqual(open(r.preserved_path, "rb").read(), b"OLD-LOCAL")
        with self.assertRaises(CP.CopyError):                      # never overwrite a preserved version
            self.cp(self.E.work("M01/p2.nii", b"THIRD"), dst, mode=CommitMode.PRESERVE_PREVIOUS, tag="jobP")
        self.assertEqual(open(r.preserved_path, "rb").read(), b"OLD-LOCAL")
        self.assertEqual(open(dst, "rb").read(), b"NEW-STAGED")

    def test_preserve_previous_rolls_back_if_the_swap_fails(self):
        src = self.E.work("M01/q.nii", b"NEW")
        dst = self.E.work("M04/q.nii", b"OLD")
        real = CP._rename_exclusive                         # 1b: publishing uses the exclusive rename
        with mock.patch.object(CP, "_rename_exclusive", side_effect=lambda a, b: (_ for _ in ()).throw(OSError(5, "EIO"))
                               if a.endswith(".part-jobQ") else real(a, b)):
            with self.assertRaises(OSError):
                self.cp(src, dst, mode=CommitMode.PRESERVE_PREVIOUS, tag="jobQ")
        self.assertEqual(open(dst, "rb").read(), b"OLD")
        self.assertFalse(os.path.exists(dst + ".replaced-jobQ"))

    def test_new_name_never_touches_the_existing_file(self):
        src = self.E.work("M01/r.nii.gz", b"FROM-VAULT")
        dst = self.E.work("M05/r.nii.gz", b"LOCAL-EDIT")
        r = self.cp(src, dst, mode=CommitMode.NEW_NAME, tag="jobR")
        self.assertEqual(r.status, "committed")
        self.assertEqual(open(dst, "rb").read(), b"LOCAL-EDIT")
        self.assertTrue(r.dst.endswith("r_restored_jobR.nii.gz"))
        self.assertEqual(open(r.dst, "rb").read(), b"FROM-VAULT")

    def test_replace_after_verify(self):
        src = self.E.work("M01/s.nii", b"NEWER")
        dst = self.E.work("M06/s.nii", b"OLDER")
        r = self.cp(src, dst, mode=CommitMode.REPLACE_AFTER_VERIFY)
        self.assertEqual(r.status, "committed")
        self.assertEqual(open(dst, "rb").read(), b"NEWER")
        self.assertEqual(sorted(os.listdir(os.path.dirname(dst))), ["s.nii"])


class TestPauseCancelAndStaleParts(CopierBase):
    def test_cancel_removes_part_and_keeps_destination(self):
        src = self.E.work("M01/t.nii", b"T" * 30000)
        dst = self.E.work("M07/t.nii", b"KEEP")
        calls = {"n": 0}

        def control():
            calls["n"] += 1
            return "cancel" if calls["n"] == 2 else None
        with self.assertRaises(CP.CopyCancelled):
            self.cp(src, dst, chunk_size=10000, control=control)
        self.assertEqual(open(dst, "rb").read(), b"KEEP")

    def test_pause_keeps_part_for_verified_resume(self):
        src = self.E.work("M01/u.nii", b"U" * 30000)
        dst = os.path.join(self.E.base, "work", "M07", "u.nii")
        calls = {"n": 0}

        def control():
            calls["n"] += 1
            return "pause" if calls["n"] == 3 else None
        with self.assertRaises(CP.CopyPaused) as cm:
            self.cp(src, dst, chunk_size=10000, control=control, tag="jobU")
        self.assertEqual(cm.exception.bytes_written, 20000)
        self.assertTrue(os.path.isfile(cm.exception.part_path))
        self.assertFalse(os.path.exists(dst))
        with self.assertRaises(CP.StalePartFile):                  # a fresh copy never adopts a stale .part
            self.cp(src, dst, tag="jobU")
        self.assertTrue(os.path.isfile(cm.exception.part_path))     # ...and never deletes it either
        os.remove(cm.exception.part_path)                           # (1c recovery will own this decision)

    def test_part_of_another_job_is_never_touched(self):
        src = self.E.work("M01/v.nii", b"V")
        dst = os.path.join(self.E.base, "work", "M08", "v.nii")
        other = _w(dst + ".part-otherjob", b"SOMEONE ELSES PARTIAL")
        r = self.cp(src, dst, tag="mine")
        self.assertEqual(r.status, "committed")
        self.assertEqual(open(other, "rb").read(), b"SOMEONE ELSES PARTIAL")
        os.remove(other)


class TestPolicyIntegration(CopierBase):
    def test_protected_destinations_are_refused(self):
        src = self.E.work("M01/w.nii", b"W")
        targets = ["raw/M01/SWI/swi.nii", "raw/M01/new.nii", "data/M01_swi.nii", "app_data/import_src/S16/a.dcm",
                   "review/M01_calls_alice.csv", "review/new.csv", "labels/x.csv", "percival/registry/v1.json",
                   "app_data/pensieve.db", "app_data/settings.json", "RAW/M01/x.nii"]
        for rel in targets:
            for mode in CommitMode:
                with self.subTest(rel=rel, mode=mode), self.assertRaises(CP.CopyRefused):
                    self.cp(src, os.path.join(self.E.base, rel), mode=mode)
        for rel in ("original_mri/M01/o.dcm", "original_mri/M01/new.dcm", "PENSIEVE/pensieve.db", "manifest/x.json"):
            with self.subTest(vault=rel), self.assertRaises(CP.CopyRefused):
                self.cp(src, os.path.join(self.E.vault, rel), mode=CommitMode.REPLACE_AFTER_VERIFY)
        with self.assertRaises(CP.CopyRefused):
            self.cp(src, os.path.join(self.E.tmp, "Volumes", "Percival", "Dicom", "M01", "c.dcm"))

    def test_sources_outside_or_links_are_refused(self):
        outside = _w(os.path.join(self.E.tmp, "outside", "o.nii"), b"O")
        with self.assertRaises(CP.CopyRefused):
            self.cp(outside, os.path.join(self.E.base, "work", "X", "o.nii"))
        link = os.path.join(self.E.base, "work", "M01", "link.nii")
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(os.path.join(self.E.base, "raw", "M01", "SWI", "swi.nii"), link)
        with self.assertRaises(CP.CopyRefused):
            self.cp(link, os.path.join(self.E.base, "work", "X", "l.nii"))
        os.remove(link)
        with self.assertRaises(CP.CopyRefused):
            self.cp(self.E.work("M01/y.nii", b"Y"), os.path.join(self.E.tmp, "outside", "y.nii"))
        for tag in ("", "../x", "a/b", "x" * 70):
            with self.subTest(tag=tag), self.assertRaises(CP.CopyRefused):
                self.cp(self.E.work("M01/z.nii", b"Z"), os.path.join(self.E.base, "work", "X", "z.nii"), tag=tag)

    def test_reading_originals_is_allowed(self):
        r = self.cp(os.path.join(self.E.base, "raw", "M01", "SWI", "swi.nii"),
                    os.path.join(self.E.base, "work", "M01", "swi_copy.nii"))
        self.assertEqual(r.status, "committed")
        r = self.cp(os.path.join(self.E.tmp, "Volumes", "Percival", "Dicom", "M01", "c.dcm"),
                    os.path.join(self.E.base, "work", "M01", "c.dcm"))
        self.assertEqual(r.status, "committed")

    def test_existing_engine_and_callers_unchanged_in_1a(self):
        import uengine.unified_transfer_engine as UTE
        self.assertFalse(hasattr(UTE, "verified_copy"))             # 1a adds new modules only; wiring is milestone 1b


if __name__ == "__main__":
    unittest.main()
