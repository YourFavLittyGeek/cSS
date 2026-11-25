"""Phase 1 milestone 1c tests: crash recovery (detect / assess / resume / discard).

Every scenario runs the job in a CHILD process that kills itself with SIGKILL at a named write-ahead boundary
(uengine/transfer/crashpoints.py, honoured only under test isolation). The parent then detects the interrupted job,
assesses it (must be read-only), resumes or discards it, checks the end state byte for byte, and repeats the recovery
call (must be a no-op). Repeated crashes DURING recovery, faults (disk full, permission, missing / changed source,
missing / changed destination, changed preserved version, unrecognized temporary files, unavailable volume) and
APFS / HFS+ / FAT32 disk images are covered. Synthetic data in temporary folders only."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_phase1a_transfer_core import Env, _w                           # noqa: E402
from uengine.transfer import copier as CP                                 # noqa: E402
from uengine.transfer import tree as TR                                   # noqa: E402
from uengine.transfer.service import TransferRefused, TransferService      # noqa: E402

PY = sys.executable
CHILD_PATH = [os.path.join(ROOT, "unified_engine"), ROOT, HERE]
CHILD = r"""
import os, sys, json, time
sys.path[:0] = %(path)r
from uengine.transfer import copier as CP
from uengine.transfer.service import TransferService
if %(slow)r:
    real = CP._hash_file
    def slow(p, nocache=False, chunk=CP.CHUNK):
        if nocache:
            print("SLOW", flush=True); time.sleep(60)
        return real(p, nocache, chunk)
    CP._hash_file = slow
svc = TransferService(%(base)r, %(vault)r)
a = %(action)r
if a == "run":
    job = svc.submit(%(op)r, %(items)r, study_id=%(study)r, mode=%(mode)r)
    print("JOB " + job, flush=True)
    print("END " + svc.run(job)["state"], flush=True)
elif a == "resume":
    print("END " + svc.resume(%(job)r)["state"], flush=True)
elif a == "discard":
    print("END " + svc.discard(%(job)r)["state"], flush=True)
"""

RUN_POINTS = ["stage.before_copy", "stage.after_part_recorded", "stage.after_verified", "mkdir.after_record",
              "commit.after_intent", "commit.after_move_aside", "commit.after_publish", "commit.after_record",
              "commit.after_publish:2", "commit.after_record:2", "move.after_intent", "move.after_remove",
              "move.after_remove:2", "finalize.after_intent", "finalize.after_remove"]

A = b"A" * 70000
B = b"B" * 250000
C = b"C" * 30


def _sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def tree_fp(root):
    """content fingerprint of a tree, excluding the journal / lock folders (assess may only READ them)"""
    out = {}
    for r, ds, fs in os.walk(root):
        ds[:] = [d for d in ds if not (r.endswith("app_data") and d in ("transfers", "locks"))]
        for f in fs:
            p = os.path.join(r, f)
            st = os.lstat(p)
            out[os.path.relpath(p, root)] = (st.st_size, st.st_mtime_ns, st.st_ino)
        for d in ds:
            out[os.path.relpath(os.path.join(r, d), root) + "/"] = "d"
    return out


class Scenario:
    """a synthetic job + the expected end states after resume / discard"""

    def __init__(self, E: Env, kind: str):
        self.E, self.kind = E, kind
        b, v = E.base, E.vault
        if kind == "archive":
            self.src = os.path.join(b, "work", "A")
            self.dst = os.path.join(v, "studies", "A")
            for n, d in (("a.nii", A), ("b.nii", B), ("c.nii", C)):
                _w(os.path.join(self.src, n), d)
            self.op, self.mode, self.study = "archive", None, "A"
        elif kind == "stage":
            self.src = os.path.join(v, "studies", "S")
            self.dst = os.path.join(b, "work", "S")
            for n, d in (("a.nii", A), ("b.nii", B), ("c.nii", C)):
                _w(os.path.join(self.src, n), d)
            _w(os.path.join(self.dst, "a.nii"), b"OLD-LOCAL-A")
            _w(os.path.join(self.dst, "b.nii"), b"OLD-LOCAL-B")
            self.op, self.mode, self.study = "stage", None, "S"
        else:
            self.src = os.path.join(b, "work", "MV")
            self.dst = os.path.join(b, "work", "MV_out")
            for n, d in (("a.nii", A), ("b.nii", B), ("c.nii", C)):
                _w(os.path.join(self.src, n), d)
            self.op, self.mode, self.study = "move", None, None
        self.content = {"a.nii": A, "b.nii": B, "c.nii": C}

    def items(self):
        return [(self.src, self.dst)]

    def no_artifacts(self, tc):
        art = [a for root in (self.E.base, self.E.vault) for a in TR.list_stale_artifacts(root)]
        tc.assertEqual(art, [], "transfer artifacts left behind")

    def check_resumed(self, tc):
        for n, d in self.content.items():
            tc.assertEqual(open(os.path.join(self.dst, n), "rb").read(), d, f"{self.kind}: {n} not complete")
        if self.kind == "move":
            for n in self.content:
                tc.assertFalse(os.path.exists(os.path.join(self.src, n)), "verified move source not removed")
        else:
            for n, d in self.content.items():
                tc.assertEqual(open(os.path.join(self.src, n), "rb").read(), d, "source changed")
        self.no_artifacts(tc)

    def check_discarded(self, tc):
        if self.kind == "archive":
            tc.assertFalse(os.path.exists(self.dst), "archive destination not removed on discard")
        elif self.kind == "stage":
            tc.assertEqual(open(os.path.join(self.dst, "a.nii"), "rb").read(), b"OLD-LOCAL-A")
            tc.assertEqual(open(os.path.join(self.dst, "b.nii"), "rb").read(), b"OLD-LOCAL-B")
            tc.assertFalse(os.path.exists(os.path.join(self.dst, "c.nii")))
        else:
            for n, d in self.content.items():
                s, t = os.path.join(self.src, n), os.path.join(self.dst, n)
                tc.assertTrue(os.path.exists(s) or os.path.exists(t), f"DATA LOSS: {n} exists nowhere")
                if os.path.exists(s):
                    tc.assertEqual(open(s, "rb").read(), d)
                    tc.assertFalse(os.path.exists(t), "discard left a destination whose source still exists")
                else:
                    tc.assertEqual(open(t, "rb").read(), d, "the only copy changed")
        for n, d in self.content.items():
            if self.kind != "move":
                tc.assertEqual(open(os.path.join(self.src, n), "rb").read(), d, "discard touched a source")
        self.no_artifacts(tc)


class Base(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.svc = TransferService(self.E.base, self.E.vault)

    def tearDown(self):
        self.svc.close()
        self.E.assert_protected_intact(self)
        self.E.close()

    def child(self, action, crash_at=None, sc=None, job=None, slow=False, vault=None, wait=True):
        code = CHILD % dict(path=CHILD_PATH, base=self.E.base, vault=vault or self.E.vault, action=action, slow=slow,
                            op=sc.op if sc else None, items=sc.items() if sc else None, study=sc.study if sc else None,
                            mode=sc.mode if sc else None, job=job)
        env = dict(os.environ)
        env.pop("PERCIVAL_TEST_CRASH_AT", None)
        if crash_at:
            env["PERCIVAL_TEST_CRASH_AT"] = crash_at
        p = subprocess.Popen([PY, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        if not wait:
            return p
        out, err = p.communicate(timeout=180)
        jid = next((l.split()[1] for l in out.splitlines() if l.startswith("JOB ")), job)
        end = next((l.split()[1] for l in out.splitlines() if l.startswith("END ")), None)
        if p.returncode not in (0, -9):
            self.fail(f"child failed rc={p.returncode}: {err[-2000:]}")
        return jid, p.returncode == -9, end

    def crash_run(self, kind, point):
        sc = Scenario(self.E, kind)
        job, killed, end = self.child("run", point, sc)
        return sc, job, killed, end

    def assess_readonly(self, job):
        before = tree_fp(self.E.tmp)
        a = self.svc.assess(job)
        self.assertEqual(tree_fp(self.E.tmp), before, "assess changed the filesystem")
        return a


# ================================================================================================ crash matrix
class TestCrashMatrix(Base):
    """SIGKILL at every write-ahead boundary of a normal run, then resume OR discard -> correct end state, twice"""
    reached = set()

    def _one(self, kind, point, decision):
        sc, job, killed, end = self.crash_run(kind, point)
        if not killed:
            self.assertEqual(end, "completed")                                    # boundary not on this job's path
            return False
        self.reached.add(point)
        self.assertEqual(self.svc.detect_interrupted(), [job])
        self.assertEqual(self.svc.detect_interrupted(), [])                       # idempotent detection
        a = self.assess_readonly(job)
        self.assertEqual(a["state"], "interrupted")
        if decision == "resume":
            self.assertTrue(a["resumable"], a)
            r = self.svc.resume(job)
            self.assertTrue(r["ok"], r)
            sc.check_resumed(self)
        elif kind == "stage" and point == "finalize.after_remove":
            # the first previous version was already removed (the job had verified everything): discard cannot bring
            # it back, keeps the committed file (only copy) and asks a human - never guesses
            r = self.svc.discard(job)
            self.assertEqual(r["state"], "needs_attention", r)
            self.assertEqual(open(os.path.join(sc.dst, "a.nii"), "rb").read(), A)
            self.assertEqual(open(os.path.join(sc.dst, "b.nii"), "rb").read(), b"OLD-LOCAL-B")
            self.assertFalse(os.path.exists(os.path.join(sc.dst, "c.nii")))
            return True
        else:
            r = self.svc.discard(job)
            self.assertEqual(r["state"], "cancelled", r)
            sc.check_discarded(self)
        fp = tree_fp(self.E.tmp)
        again = (self.svc.resume if decision == "resume" else self.svc.discard)(job)
        self.assertTrue(again.get("noop"), again)                                  # idempotent
        self.assertEqual(tree_fp(self.E.tmp), fp)
        return True

    def test_matrix(self):
        ran = 0
        for kind in ("archive", "stage", "move"):
            for point in RUN_POINTS:
                for decision in ("resume", "discard"):
                    with self.subTest(kind=kind, point=point, decision=decision):
                        self.svc.close()
                        self.E.close()
                        self.E = Env()
                        self.svc = TransferService(self.E.base, self.E.vault)
                        ran += self._one(kind, point, decision)
        self.assertEqual(self.reached, {p for p in RUN_POINTS}, f"boundaries never reached: {set(RUN_POINTS) - self.reached}")
        self.assertGreaterEqual(ran, 50)


# ================================================================================================ crashes during recovery
class TestRepeatedCrashes(Base):
    def test_resume_crashes_twice_then_completes(self):
        sc, job, killed, _ = self.crash_run("archive", "commit.after_record:2")
        self.assertTrue(killed)
        for point in ("recover.after_decision", "commit.after_intent", "commit.after_publish"):
            was = self.svc.journal.get_job(job)["state"]
            self.assertEqual(self.svc.detect_interrupted(), [] if was == "interrupted" else [job])
            self.assertEqual(self.svc.journal.get_job(job)["state"], "interrupted")
            _, k, _ = self.child("resume", point, job=job)
            self.assertTrue(k, point)
            self.assertEqual(self.svc.journal.get_job(job)["recovery_decision"], "resume")
        self.svc.detect_interrupted()
        with self.assertRaises(TransferRefused):                                   # the decision cannot be switched
            self.svc.discard(job)
        r = self.svc.resume(job)
        self.assertTrue(r["ok"], r)
        sc.check_resumed(self)

    def test_discard_crashes_at_each_undo_step_then_completes(self):
        sc, job, killed, _ = self.crash_run("stage", "commit.after_record:2")
        self.assertTrue(killed)
        for point in ("undo.after_intent", "undo.after_remove", "undo.after_restore", "undo.after_remove:2"):
            self.svc.detect_interrupted()
            _, k, end = self.child("discard", point, job=job)
            if not k:
                self.assertEqual(end, "cancelled")
                break
        self.svc.detect_interrupted()
        r = self.svc.discard(job)
        self.assertIn(r["state"], ("cancelled",), r)
        sc.check_discarded(self)
        self.assertTrue(self.svc.discard(job)["noop"])

    def test_move_discard_after_sources_partly_removed_never_loses_data(self):
        sc, job, killed, _ = self.crash_run("move", "move.after_remove:2")
        self.assertTrue(killed)
        self.svc.detect_interrupted()
        r = self.svc.discard(job)
        self.assertEqual(r["state"], "cancelled", r)
        self.assertEqual(len(r["kept_only_copy"]), 2)                              # two sources were already gone
        sc.check_discarded(self)

    def test_live_job_is_never_marked_interrupted(self):
        sc = Scenario(self.E, "archive")
        p = self.child("run", sc=sc, slow=True, wait=False)
        t0 = time.time()
        job = None
        while time.time() - t0 < 60:
            line = p.stdout.readline()
            if line.startswith("JOB "):
                job = line.split()[1]
            if line.startswith("SLOW"):
                break
        self.assertEqual(self.svc.detect_interrupted(), [])                       # owner alive: lock held
        p.kill()
        p.wait(timeout=30)
        self.assertEqual(self.svc.detect_interrupted(), [job])
        self.assertTrue(self.svc.discard(job)["ok"])
        sc.check_discarded(self)


# ================================================================================================ faults and ambiguity
class TestFaults(Base):
    def interrupted(self, kind, point):
        sc, job, killed, _ = self.crash_run(kind, point)
        self.assertTrue(killed, point)
        self.assertEqual(self.svc.detect_interrupted(), [job])
        return sc, job

    def test_disk_full_while_resuming_then_retry(self):
        sc, job = self.interrupted("archive", "stage.after_verified")
        real = CP.stage_file
        with mock.patch.object(CP, "stage_file", side_effect=OSError(errno.ENOSPC, "No space left on device (simulated)")):
            r = self.svc.resume(job)
        self.assertEqual(r["state"], "interrupted")
        self.assertIn("No space left", r["errors"][-1])
        self.assertIs(CP.stage_file, real)
        first = self.svc.journal.get_files(job)[0]
        self.assertEqual(first["state"], "verified")                               # earlier verified work kept
        self.assertTrue(os.path.exists(first["part_path"]))
        self.assertFalse(os.path.exists(os.path.join(sc.dst, "a.nii")))           # nothing published by the failed try
        r = self.svc.resume(job)
        self.assertTrue(r["ok"], r)
        sc.check_resumed(self)

    def test_permission_denied_while_resuming_then_retry(self):
        sc, job = self.interrupted("archive", "commit.after_record")
        os.chmod(sc.dst, 0o555)
        try:
            r = self.svc.resume(job)
            self.assertEqual(r["state"], "interrupted")
        finally:
            os.chmod(sc.dst, 0o755)
        r = self.svc.resume(job)
        self.assertTrue(r["ok"], r)
        sc.check_resumed(self)

    def test_missing_source_blocks_resume_and_discard_keeps_other_sources(self):
        sc, job = self.interrupted("archive", "stage.after_verified")
        os.remove(os.path.join(sc.src, "b.nii"))
        a = self.assess_readonly(job)
        self.assertFalse(a["resumable"])
        self.assertIn("source_missing", {x["reason"] for x in a["ambiguous"]})
        fp = tree_fp(self.E.tmp)
        with self.assertRaises(TransferRefused):
            self.svc.resume(job)
        self.assertEqual(tree_fp(self.E.tmp), fp)                                 # refusal changes nothing
        self.assertEqual(self.svc.discard(job)["state"], "cancelled")
        self.assertFalse(os.path.exists(sc.dst))
        self.assertEqual(open(os.path.join(sc.src, "a.nii"), "rb").read(), A)

    def test_changed_source_blocks_resume(self):
        sc, job = self.interrupted("archive", "stage.after_verified")
        with open(os.path.join(sc.src, "a.nii"), "ab") as f:
            f.write(b"edited")
        a = self.assess_readonly(job)
        self.assertIn("source_changed", {x["reason"] for x in a["ambiguous"]})
        with self.assertRaises(TransferRefused):
            self.svc.resume(job)
        self.assertEqual(self.svc.discard(job)["state"], "cancelled")
        self.assertTrue(open(os.path.join(sc.src, "a.nii"), "rb").read().endswith(b"edited"))   # source never touched

    def test_missing_destination_blocks_resume(self):
        sc, job = self.interrupted("archive", "commit.after_record:2")
        os.remove(os.path.join(sc.dst, "a.nii"))
        a = self.assess_readonly(job)
        self.assertIn("destination_missing", {x["reason"] for x in a["ambiguous"]})
        with self.assertRaises(TransferRefused):
            self.svc.resume(job)
        self.assertEqual(self.svc.discard(job)["state"], "cancelled")
        self.assertFalse(os.path.exists(sc.dst))

    def test_changed_destination_is_never_deleted(self):
        sc, job = self.interrupted("archive", "commit.after_record:2")
        with open(os.path.join(sc.dst, "a.nii"), "ab") as f:
            f.write(b"someone else's edit")
        a = self.assess_readonly(job)
        self.assertIn("destination_changed", {x["reason"] for x in a["ambiguous"]})
        with self.assertRaises(TransferRefused):
            self.svc.resume(job)
        r = self.svc.discard(job)
        self.assertEqual(r["state"], "cancelled", r)
        self.assertTrue(open(os.path.join(sc.dst, "a.nii"), "rb").read().endswith(b"someone else's edit"))
        self.assertFalse(os.path.exists(os.path.join(sc.dst, "b.nii")))           # ours -> removed
        self.assertIn(os.path.join(sc.dst, "a.nii"), [x["path"] for x in r["left_untouched"]])

    def test_unrecorded_publish_with_rewritten_content_is_not_trusted(self):
        """identity alone is not proof: a file rewritten in place with its timestamp reset is caught by the hash"""
        sc, job = self.interrupted("archive", "commit.after_publish")
        p = os.path.join(sc.dst, "a.nii")
        st = os.stat(p)
        with open(p, "r+b") as f:
            f.write(b"Z")                                                    # same size, different content
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))                     # identity (size, mtime, inode) unchanged
        a = self.assess_readonly(job)
        self.assertIn("destination_changed", {x["reason"] for x in a["ambiguous"]})
        with self.assertRaises(TransferRefused):
            self.svc.resume(job)
        r = self.svc.discard(job)
        self.assertTrue(open(p, "rb").read().startswith(b"Z"))               # not provably ours -> never deleted
        self.assertIn(p, [x["path"] for x in r["left_untouched"]])

    def test_changed_preserved_version_needs_a_human(self):
        sc, job = self.interrupted("stage", "commit.after_record")
        rec = self.svc.journal.get_files(job)[0]
        with open(rec["preserved_path"], "ab") as f:
            f.write(b"!")
        a = self.assess_readonly(job)
        self.assertIn("preserved_changed", {x["reason"] for x in a["ambiguous"]})
        with self.assertRaises(TransferRefused):
            self.svc.resume(job)
        r = self.svc.discard(job)
        self.assertEqual(r["state"], "needs_attention", r)
        self.assertTrue(open(rec["preserved_path"], "rb").read().endswith(b"!"))   # never deleted
        os.remove(rec["preserved_path"])

    def test_unrecognized_temporary_file_is_never_deleted(self):
        sc, job = self.interrupted("archive", "stage.before_copy")
        rec = self.svc.journal.get_files(job)[0]
        planted = _w(rec["part_path"], b"NOT PERCIVAL'S")
        a = self.assess_readonly(job)
        self.assertTrue(any("unrecognized" in n for n in a["notes"]), a["notes"])
        r = self.svc.resume(job)
        self.assertTrue(r["ok"], r)
        self.assertEqual(open(planted, "rb").read(), b"NOT PERCIVAL'S")
        for n, d in sc.content.items():
            self.assertEqual(open(os.path.join(sc.dst, n), "rb").read(), d)
        os.remove(planted)
        sc.no_artifacts(self)

    def test_own_partial_part_is_recognized_and_cleaned(self):
        sc, job = self.interrupted("archive", "stage.after_part_recorded")
        rec = self.svc.journal.get_files(job)[0]
        self.assertTrue(os.path.exists(rec["part_path"]))
        self.assertEqual(self.svc.discard(job)["state"], "cancelled")
        self.assertFalse(os.path.exists(rec["part_path"]))
        sc.check_discarded(self)

    def test_recovery_of_a_v1_journal_job_is_refused_not_guessed(self):
        sc, job = self.interrupted("archive", "commit.after_record")
        con = __import__("sqlite3").connect(self.svc.journal.path)
        con.execute("UPDATE job_files SET dst_identity=NULL, part_identity=NULL WHERE job_id=?", (job,))   # 1b-style rows
        con.commit()
        con.close()
        a = self.assess_readonly(job)
        self.assertFalse(a["resumable"])
        r = self.svc.discard(job)
        self.assertTrue(os.path.exists(os.path.join(sc.dst, "a.nii")))           # unproven -> never deleted
        self.assertIn(r["state"], ("cancelled", "needs_attention"))

    def test_schema_v1_journal_is_migrated_in_place(self):
        import sqlite3
        self.svc.close()
        p = os.path.join(self.E.base, "app_data", "transfers", "journal.db")
        os.remove(p)
        for x in ("-wal", "-shm"):
            if os.path.exists(p + x):
                os.remove(p + x)
        con = sqlite3.connect(p)                                                   # a genuine 1b (schema v1) journal
        con.executescript("""
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta VALUES ('schema_version', '1');
            CREATE TABLE jobs (job_id TEXT PRIMARY KEY, operation TEXT NOT NULL, study_id TEXT, commit_mode TEXT NOT NULL,
                state TEXT NOT NULL, spec_json TEXT NOT NULL, total_files INTEGER NOT NULL DEFAULT 0, total_bytes INTEGER NOT NULL DEFAULT 0,
                done_files INTEGER NOT NULL DEFAULT 0, done_bytes INTEGER NOT NULL DEFAULT 0, phase_bytes INTEGER NOT NULL DEFAULT 0,
                current_file TEXT, error TEXT, owner_pid INTEGER, heartbeat REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL);
            CREATE TABLE job_files (job_id TEXT NOT NULL REFERENCES jobs(job_id), seq INTEGER NOT NULL, rel_path TEXT NOT NULL,
                src TEXT NOT NULL, dst TEXT NOT NULL, size INTEGER NOT NULL, state TEXT NOT NULL, src_mtime_ns INTEGER, src_ino INTEGER,
                src_sha256 TEXT, part_path TEXT, part_sha256 TEXT, dst_sha256 TEXT, committed_path TEXT, preserved_path TEXT,
                error TEXT, updated_at REAL NOT NULL, PRIMARY KEY (job_id, seq));
            CREATE TABLE job_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(job_id),
                ts REAL NOT NULL, kind TEXT NOT NULL, seq INTEGER, from_state TEXT, to_state TEXT, detail_json TEXT);
            INSERT INTO jobs VALUES ('old-job', 'copy', NULL, 'new_name', 'completed', '{}', 1, 1, 1, 1, 0, NULL, NULL, NULL, NULL, 1, 1);
        """)
        con.commit()
        con.close()
        self.svc = TransferService(self.E.base, self.E.vault)
        con = sqlite3.connect(p)
        from uengine.transfer.journal import SCHEMA_VERSION
        self.assertEqual(con.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0], str(SCHEMA_VERSION))
        self.assertIn("control", {r[1] for r in con.execute("PRAGMA table_info(jobs)")})          # v3 (1d)
        self.assertEqual(con.execute("SELECT value FROM schema_meta WHERE key='migrated_from'").fetchone()[0], "1")
        cols = {r[1] for r in con.execute("PRAGMA table_info(job_files)")}
        self.assertTrue({"src_identity", "part_identity", "dst_identity", "old_identity", "preserved_state", "intent", "attempt"} <= cols)
        self.assertEqual(con.execute("SELECT state FROM jobs WHERE job_id='old-job'").fetchone()[0], "completed")   # data kept
        con.close()
        self.assertEqual(self.svc.journal.get_job("old-job")["created_dirs"], "[]")


# ================================================================================================ filesystems + volumes
class TestFilesystemsAndVolumes(unittest.TestCase):
    FS = {"apfs": "APFS", "hfs": "HFS+", "msdos": "MS-DOS FAT32", "exfat": "ExFAT"}

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="p1c_fs_")
        cls.imgs, cls.mounts = {}, {}
        if not shutil.which("hdiutil"):
            return
        for key, fs in cls.FS.items():
            img, mnt = os.path.join(cls.root, f"{key}.dmg"), os.path.join(cls.root, f"mnt_{key}")
            os.makedirs(mnt)
            if subprocess.run(["hdiutil", "create", "-quiet", "-size", "48m", "-fs", fs, "-volname", f"P1C{key}", img],
                              capture_output=True).returncode == 0:
                cls.imgs[key] = img
                if cls._attach(img, mnt):
                    cls.mounts[key] = mnt

    @staticmethod
    def _attach(img, mnt):
        subprocess.run(["hdiutil", "attach", "-quiet", "-nobrowse", "-noverify", "-mountpoint", mnt, img], capture_output=True)
        return os.path.ismount(mnt)

    @classmethod
    def tearDownClass(cls):
        for mnt in cls.mounts.values():
            if os.path.ismount(mnt):
                subprocess.run(["hdiutil", "detach", "-quiet", mnt], capture_output=True)
            if os.path.ismount(mnt):
                subprocess.run(["hdiutil", "detach", "-quiet", "-force", mnt], capture_output=True)
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.E = Env()

    def tearDown(self):
        self.E.assert_protected_intact(self)
        self.E.close()

    def mnt(self, key):
        if key not in self.mounts:
            self.skipTest(f"{key} image unavailable")
        return self.mounts[key]

    def _crash_archive(self, vault, point):
        src = os.path.join(self.E.base, "work", "FS")
        for n, d in (("a.nii", A), ("b.nii", B), ("c.nii", C)):
            _w(os.path.join(src, n), d)
        dst = os.path.join(vault, "studies", "FS")
        code = CHILD % dict(path=CHILD_PATH, base=self.E.base, vault=vault, action="run", slow=False, op="archive",
                            items=[(src, dst)], study="FS", mode=None, job=None)
        env = dict(os.environ, PERCIVAL_TEST_CRASH_AT=point)
        out = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=180).stdout
        return next(l.split()[1] for l in out.splitlines() if l.startswith("JOB ")), src, dst

    def test_recovery_on_each_supported_filesystem(self):
        for key in ("apfs", "hfs", "msdos"):
            for decision in ("resume", "discard"):
                with self.subTest(fs=key, decision=decision):
                    vault = os.path.join(self.mnt(key), f"PERCIVAL_VAULT_{decision}")
                    os.makedirs(os.path.join(vault, "studies"), exist_ok=True)
                    job, src, dst = self._crash_archive(vault, "commit.after_publish:2")
                    svc = TransferService(self.E.base, vault)
                    try:
                        self.assertEqual(svc.detect_interrupted(), [job])
                        r = svc.resume(job) if decision == "resume" else svc.discard(job)
                        self.assertTrue(r["ok"], r)
                        if decision == "resume":
                            for n, d in (("a.nii", A), ("b.nii", B), ("c.nii", C)):
                                self.assertEqual(open(os.path.join(dst, n), "rb").read(), d)
                        else:
                            self.assertFalse(os.path.exists(dst))
                        self.assertEqual(TR.list_stale_artifacts(vault), [])
                    finally:
                        svc.close()
                    shutil.rmtree(src)

    @mock.patch.dict(os.environ, {"CSS_EXFAT_STRICT": "1"})      # the old refusal, still available (CSS_EXFAT_STRICT=1)
    def test_exfat_archive_refusal_unchanged(self):
        vault = os.path.join(self.mnt("exfat"), "PERCIVAL_VAULT")
        os.makedirs(os.path.join(vault, "studies"), exist_ok=True)
        svc = TransferService(self.E.base, vault)
        try:
            with self.assertRaises(TransferRefused):
                svc.transfer("archive", [(self.E.work("M01/x.nii", b"x"), os.path.join(vault, "studies", "M01", "x.nii"))])
        finally:
            svc.close()

    def test_unavailable_volume_is_refused_then_recovered_after_remount(self):
        mnt = self.mnt("apfs")
        vault = os.path.join(mnt, "PERCIVAL_VAULT_unplug")
        os.makedirs(os.path.join(vault, "studies"), exist_ok=True)
        job, src, dst = self._crash_archive(vault, "commit.after_record:2")
        svc = TransferService(self.E.base, vault)
        try:
            self.assertEqual(svc.detect_interrupted(), [job])
            subprocess.run(["hdiutil", "detach", "-quiet", mnt], capture_output=True)
            self.assertFalse(os.path.isdir(vault))
            before = svc.journal.events(job)
            a = svc.assess(job)
            self.assertTrue(a["unavailable"])
            self.assertFalse(a["resumable"] or a["discardable"])
            with self.assertRaises(TransferRefused):
                svc.resume(job)
            with self.assertRaises(TransferRefused):
                svc.discard(job)
            self.assertEqual(svc.journal.events(job), before)                     # refusal recorded nothing
            self.assertTrue(self._attach(self.imgs["apfs"], mnt))
            r = svc.resume(job)
            self.assertTrue(r["ok"], r)
            for n, d in (("a.nii", A), ("b.nii", B), ("c.nii", C)):
                self.assertEqual(open(os.path.join(dst, n), "rb").read(), d)
        finally:
            svc.close()
            if not os.path.ismount(mnt):
                self._attach(self.imgs["apfs"], mnt)
        shutil.rmtree(src)


if __name__ == "__main__":
    unittest.main()
