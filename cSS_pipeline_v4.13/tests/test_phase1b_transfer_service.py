"""Phase 1 milestone 1b tests: exclusive commit per filesystem, tree handling, journal-backed jobs, rollback, races.

Isolated (tests/_isolation.py). Real filesystems are exercised on small DISK IMAGES created and mounted inside the
temporary test tree (hdiutil; never /Volumes, never a physical drive) - skipped if hdiutil is unavailable. A synthetic
protected tree (original MRI, reader calls, call ledger, labels, model store, Pensieve, Vault originals) must stay
byte-identical."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_phase1a_transfer_core import Env, _w, _sha                     # noqa: E402  (shared synthetic project)
from uengine.safety import PathPolicy                                    # noqa: E402
from uengine.transfer import copier as CP                                # noqa: E402
from uengine.transfer import tree as TR                                  # noqa: E402
from uengine.transfer.models import CommitMode, FileState, JobState       # noqa: E402
from uengine.transfer.service import TransferRefused, TransferService     # noqa: E402

PY = sys.executable
CHILD_PATH = [os.path.join(ROOT, "unified_engine"), ROOT, HERE]


class Base(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.svc = TransferService(self.E.base, self.E.vault)

    def tearDown(self):
        self.svc.close()
        self.E.assert_protected_intact(self)
        stray = [os.path.join(r, f) for r, ds, fs in os.walk(self.E.tmp) for f in fs + ds
                 if ".part-" in f or ".incoming-" in f]
        self.assertEqual(stray, [], "a transfer artifact was left behind")
        self.E.close()

    def tree(self, rel, files):
        root = os.path.join(self.E.base, "work", rel)
        for r, d in files.items():
            _w(os.path.join(root, r), d)
        return root

    def job_files(self, job_id):
        return {f["rel_path"]: f["state"] for f in self.svc.journal.get_files(job_id)}


# ================================================================================================ filesystems
class TestFilesystems(unittest.TestCase):
    """real APFS / HFS+ / FAT32 / exFAT behaviour on disk images mounted in the temporary test tree"""
    FS = {"apfs": "APFS", "hfs": "HFS+", "msdos": "MS-DOS FAT32", "exfat": "ExFAT"}

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="p1b_fs_")
        cls.mounts = {}
        if not shutil.which("hdiutil"):
            return
        for key, fs in cls.FS.items():
            img, mnt = os.path.join(cls.root, f"{key}.dmg"), os.path.join(cls.root, f"mnt_{key}")
            os.makedirs(mnt)
            r1 = subprocess.run(["hdiutil", "create", "-quiet", "-size", "48m", "-fs", fs, "-volname", f"P1B{key}", img], capture_output=True)
            r2 = subprocess.run(["hdiutil", "attach", "-quiet", "-nobrowse", "-noverify", "-mountpoint", mnt, img], capture_output=True) \
                if r1.returncode == 0 else r1
            if r2.returncode == 0 and os.path.ismount(mnt):
                cls.mounts[key] = mnt

    @classmethod
    def tearDownClass(cls):
        for mnt in cls.mounts.values():
            subprocess.run(["hdiutil", "detach", "-quiet", mnt], capture_output=True)
            if os.path.ismount(mnt):
                subprocess.run(["hdiutil", "detach", "-quiet", "-force", mnt], capture_output=True)
        shutil.rmtree(cls.root, ignore_errors=True)

    def mnt(self, key):
        if key not in self.mounts:
            self.skipTest(f"{key} disk image not available on this system")
        return self.mounts[key]

    def setUp(self):
        self.E = Env()

    def tearDown(self):
        self.E.assert_protected_intact(self)
        self.E.close()

    def vault_on(self, key):
        v = os.path.join(self.mnt(key), f"PERCIVAL_VAULT_{os.getpid()}_{id(self)}")
        os.makedirs(os.path.join(v, "studies"), exist_ok=True)
        return v

    def test_detected_types(self):
        for key in self.FS:
            with self.subTest(fs=key):
                self.assertEqual(CP.fs_type(self.mnt(key)), key)

    def test_exclusive_rename_primitive_per_filesystem(self):
        for key in self.FS:
            with self.subTest(fs=key):
                d = os.path.join(self.mnt(key), f"prim_{id(self)}")
                os.makedirs(d)
                _w(os.path.join(d, "old"), b"OLD")
                _w(os.path.join(d, "new.part"), b"NEW")
                with self.assertRaises(FileExistsError):                       # every filesystem: never onto an existing file
                    CP._rename_exclusive(os.path.join(d, "new.part"), os.path.join(d, "old"))
                self.assertEqual(open(os.path.join(d, "old"), "rb").read(), b"OLD")
                if key == "exfat":
                    with mock.patch.dict(os.environ, {"CSS_EXFAT_STRICT": "1"}):
                        with self.assertRaises(CP.ExclusiveCommitUnsupported):  # strict: no atomic primitive -> refused
                            CP._rename_exclusive(os.path.join(d, "new.part"), os.path.join(d, "fresh"))
                    self.assertFalse(os.path.exists(os.path.join(d, "fresh")))
                    self.assertTrue(os.path.exists(os.path.join(d, "new.part")))
                    self.assertIn("guarded", CP._rename_exclusive(os.path.join(d, "new.part"), os.path.join(d, "fresh")))
                    self.assertEqual(open(os.path.join(d, "fresh"), "rb").read(), b"NEW")
                else:
                    CP._rename_exclusive(os.path.join(d, "new.part"), os.path.join(d, "fresh"))
                    self.assertEqual(open(os.path.join(d, "fresh"), "rb").read(), b"NEW")

    @mock.patch.dict(os.environ, {"CSS_EXFAT_STRICT": "1"})      # the old refusal, still available (CSS_EXFAT_STRICT=1)
    def test_exfat_destination_refused_before_anything_is_written(self):
        v = self.vault_on("exfat")
        svc = TransferService(self.E.base, v)
        try:
            src = self.E.work("M01/a.nii", b"DATA")
            before = sorted(os.listdir(os.path.join(v, "studies")))
            for op, mode in (("archive", None), ("copy", "replace_after_verify"), ("copy", "new_name"), ("stage", None)):
                with self.subTest(op=op, mode=mode):
                    with self.assertRaises(TransferRefused) as cm:
                        svc.transfer(op, [(src, os.path.join(v, "studies", "M01", "a.nii"))], mode=mode)
                    self.assertIn("exfat", str(cm.exception))
                    self.assertIn("never overwritten", str(cm.exception))
            self.assertEqual(sorted(os.listdir(os.path.join(v, "studies"))), before)
        finally:
            svc.close()

    @mock.patch.dict(os.environ, {"CSS_EXFAT_STRICT": "1"})      # the old refusal, still available (CSS_EXFAT_STRICT=1)
    def test_exfat_commit_refused_even_if_preflight_is_bypassed(self):
        v = self.vault_on("exfat")
        pol = PathPolicy(self.E.base, v)
        src = self.E.work("M01/b.nii", b"DATA")
        dst = os.path.join(v, "studies", "M01", "b.nii")
        with mock.patch.object(CP, "NO_EXCLUSIVE_COMMIT_FS", frozenset()):
            staged = CP.stage_file(src, dst, policy=pol, job_tag="jx", mode=CommitMode.NEVER_OVERWRITE)
            with self.assertRaises(CP.ExclusiveCommitUnsupported):
                CP.commit_staged(staged, CommitMode.NEVER_OVERWRITE, policy=pol)
        self.assertFalse(os.path.exists(dst))
        self.assertFalse(os.path.exists(staged.part))

    def test_exfat_guarded_archive_writes_verified_and_never_overwrites(self):
        """2026-11-25 guarded commit: archiving to exFAT works, an existing archived file is never replaced"""
        v = self.vault_on("exfat")
        svc = TransferService(self.E.base, v)
        try:
            src = self.E.work("M01/g.nii", b"GUARDED-DATA")
            dst = os.path.join(v, "studies", "M01", "g.nii")
            rep = svc.transfer("archive", [(src, dst)], study_id="M01")
            self.assertTrue(rep["ok"], rep)
            self.assertEqual(open(dst, "rb").read(), b"GUARDED-DATA")
            self.assertEqual([n for n in os.listdir(os.path.dirname(dst)) if ".part" in n], [])
            src2 = self.E.work("M01b/g.nii", b"OTHER-CONTENT")
            rep2 = svc.transfer("archive", [(src2, dst)], study_id="M01")
            self.assertFalse(rep2["ok"], rep2)
            self.assertEqual(open(dst, "rb").read(), b"GUARDED-DATA")              # archive unchanged
        finally:
            svc.close()

    def test_exfat_guarded_commit_loses_a_race_without_overwriting(self):
        """a file appearing at the last moment before the guarded rename is never replaced"""
        v = self.vault_on("exfat")
        pol = PathPolicy(self.E.base, v)
        src = self.E.work("M01/r.nii", b"MINE")
        dst = os.path.join(v, "studies", "M01", "r.nii")
        staged = CP.stage_file(src, dst, policy=pol, job_tag="jr", mode=CommitMode.NEVER_OVERWRITE)
        r = CP.commit_staged(staged, CommitMode.NEVER_OVERWRITE, policy=pol, _before_commit=lambda: _w(dst, b"THEIRS"))
        self.assertEqual(r.status, "conflict")
        self.assertEqual(open(dst, "rb").read(), b"THEIRS")
        self.assertFalse(os.path.exists(staged.part))

    def test_reading_from_exfat_is_allowed(self):
        v = self.vault_on("exfat")
        orig = _w(os.path.join(v, "original_mri", "M01", "o.dcm"), b"EXFAT-ORIGINAL")
        svc = TransferService(self.E.base, v)
        try:
            rep = svc.transfer("stage", [(os.path.dirname(orig), os.path.join(self.E.base, "work", "M01"))], study_id="M01")
        finally:
            svc.close()
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(open(os.path.join(self.E.base, "work", "M01", "o.dcm"), "rb").read(), b"EXFAT-ORIGINAL")
        self.assertEqual(open(orig, "rb").read(), b"EXFAT-ORIGINAL")

    def test_never_overwrite_archive_on_supported_filesystems(self):
        for key in ("apfs", "hfs", "msdos"):
            with self.subTest(fs=key):
                v = self.vault_on(key)
                svc = TransferService(self.E.base, v)
                try:
                    src = self.E.work(f"{key}/a.nii", b"FIRST")
                    dst = os.path.join(v, "studies", "M01", "a.nii")
                    self.assertTrue(svc.transfer("archive", [(src, dst)])["ok"])
                    _w(src, b"SECOND-DIFFERENT")
                    rep = svc.transfer("archive", [(src, dst)])
                    self.assertEqual(rep["state"], "needs_attention")
                    self.assertEqual(open(dst, "rb").read(), b"FIRST")
                    self.assertEqual([n for n in os.listdir(os.path.dirname(dst)) if ".part-" in n], [])
                finally:
                    svc.close()


# ================================================================================================ tree handling
class TestTreeHandling(Base):
    def test_hidden_files_empty_folders_metadata_and_artifacts(self):
        src = self.tree("T1", {"a.nii": b"A", ".hidden_marker": b"H", "sub/.DS_Store": b"F", "sub/._a.nii": b"AD",
                               "sub/b.nii": b"B", "old.part": b"P", "c.nii.part-oldjob": b"P", "d.nii.replaced-oldjob": b"R",
                               "only_meta/.DS_Store": b"F"})
        os.makedirs(os.path.join(src, "empty", "nested_empty"))
        os.makedirs(os.path.join(src, "e.incoming-oldjob"))
        plan = TR.plan_tree(src, "/dst")
        self.assertEqual(sorted(f.rel for f in plan.files), [".hidden_marker", "a.nii", "sub/b.nii"])
        self.assertEqual(sorted(plan.empty_dirs), ["empty/nested_empty", "only_meta"])
        reasons = {s["rel"]: s["reason"] for s in plan.skipped}
        self.assertEqual(reasons["sub/.DS_Store"], "finder_metadata")
        self.assertEqual(reasons["sub/._a.nii"], "finder_metadata")
        for a in ("old.part", "c.nii.part-oldjob", "d.nii.replaced-oldjob", "e.incoming-oldjob"):
            self.assertEqual(reasons[a], "transfer_artifact")
        dst = os.path.join(self.E.base, "work", "T1_copy")
        rep = self.svc.transfer("copy", [(src, dst)])
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(open(os.path.join(dst, ".hidden_marker"), "rb").read(), b"H")
        self.assertTrue(os.path.isdir(os.path.join(dst, "empty", "nested_empty")))
        self.assertTrue(os.path.isdir(os.path.join(dst, "only_meta")))
        self.assertFalse(os.path.exists(os.path.join(dst, "sub", ".DS_Store")))
        self.assertFalse(os.path.exists(os.path.join(dst, "c.nii.part-oldjob")))
        stale = {os.path.basename(x["path"]): x for x in TR.list_stale_artifacts(src)}
        self.assertEqual(stale["c.nii.part-oldjob"]["job"], "oldjob")
        self.assertIn("old.part", stale)
        for n in ("c.nii.part-oldjob", "d.nii.replaced-oldjob", "old.part"):     # reported, never deleted
            self.assertTrue(os.path.exists(os.path.join(src, n)))
        for n in ("c.nii.part-oldjob", "old.part", "d.nii.replaced-oldjob"):
            os.remove(os.path.join(src, n))
        os.rmdir(os.path.join(src, "e.incoming-oldjob"))

    def test_symlinks_are_never_followed_or_copied(self):
        src = self.tree("T2", {"a.nii": b"A"})
        os.symlink(os.path.join(self.E.base, "raw", "M01", "SWI", "swi.nii"), os.path.join(src, "file_link"))
        os.symlink(os.path.join(self.E.base, "raw"), os.path.join(src, "dir_link"))
        os.symlink(os.path.join(src, "loop"), os.path.join(src, "loop"))
        os.symlink("/nonexistent/target", os.path.join(src, "dangling"))
        dst = os.path.join(self.E.base, "work", "T2_copy")
        rep = self.svc.transfer("copy", [(src, dst)])
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(sorted(os.listdir(dst)), ["a.nii"])
        self.assertEqual(sorted(s["rel"] for s in rep["skipped"] if s["reason"] == "symlink"), ["dangling", "dir_link", "file_link", "loop"])
        with self.assertRaises(TransferRefused):                                   # a link as the job root is refused
            self.svc.transfer("copy", [(os.path.join(src, "dir_link"), os.path.join(self.E.base, "work", "T2_x"))])

    def test_traversal_and_case_insensitive_protected_destinations(self):
        src = self.E.work("M01/a.nii", b"A")
        for dst in ("work/../raw/M01/x.nii", "RAW/M01/x.nii", "Data/x.nii", "Review/M01_calls_bob.csv", "LABELS/x.csv",
                    "Historical/M01/x", "PERCIVAL/x.json", "App_Data/Import_Src/S16/x", "app_data/settings.json"):
            with self.subTest(dst=dst), self.assertRaises(TransferRefused):
                self.svc.transfer("copy", [(src, os.path.join(self.E.base, dst))])
        for dst in ("Original_MRI/M01/x.dcm", "pensieve/x.db", "MANIFEST/x"):
            with self.subTest(vault=dst), self.assertRaises(TransferRefused):
                self.svc.transfer("archive", [(src, os.path.join(self.E.vault, dst))])
        for src_rel in ("raw/M01", "RAW/M01", "Review", "data"):                  # moving originals / reader records away
            with self.subTest(move=src_rel), self.assertRaises(TransferRefused):
                self.svc.transfer("move", [(os.path.join(self.E.base, src_rel), os.path.join(self.E.base, "work", "stolen"))])
        with self.assertRaises(TransferRefused):
            self.svc.transfer("copy", [(os.path.join(self.E.tmp, "outside"), os.path.join(self.E.base, "work", "x"))])
        with self.assertRaises(TransferRefused):                                   # two sources -> one destination name
            self.svc.transfer("copy", [(self.E.work("M01/A.nii", b"1"), os.path.join(self.E.base, "work", "D", "a.nii")),
                                       (self.E.work("M01/b.nii", b"2"), os.path.join(self.E.base, "work", "D", "A.NII"))])


# ================================================================================================ jobs + journal
class TestJobs(Base):
    def test_journal_records_the_full_lifecycle(self):
        src = self.tree("J1", {"a.nii": b"A" * 1000, "b.nii": b"B" * 2000})
        dst = os.path.join(self.E.vault, "studies", "J1")
        rep = self.svc.transfer("archive", [(src, dst)], study_id="J1")
        self.assertTrue(rep["ok"], rep)
        job = self.svc.journal.get_job(rep["job_id"])
        self.assertEqual((job["state"], job["done_files"], job["done_bytes"]), ("completed", 2, 3000))
        seen = [e["to_state"] for e in self.svc.journal.events(rep["job_id"]) if e["kind"] == "state"]
        self.assertEqual(seen[:2], ["preparing", "copying"])
        self.assertIn("flushing", seen)
        self.assertIn("verifying", seen)
        self.assertEqual(seen[-2:], ["committing", "completed"])
        self.assertEqual(set(self.job_files(rep["job_id"]).values()), {"committed"})
        for f in self.svc.journal.get_files(rep["job_id"]):
            self.assertEqual(f["src_sha256"], f["part_sha256"])
            self.assertEqual(f["src_sha256"], _sha(f["dst"]))

    def test_archive_conflict_writes_nothing_at_all(self):
        src = self.tree("J2", {"a.nii": b"NEW-A", "b.nii": b"NEW-B", "c.nii": b"SAME"})
        dst = os.path.join(self.E.vault, "studies", "J2")
        _w(os.path.join(dst, "b.nii"), b"ARCHIVED-B")
        _w(os.path.join(dst, "c.nii"), b"SAME")
        rep = self.svc.transfer("archive", [(src, dst)], study_id="J2")
        self.assertEqual(rep["state"], "needs_attention")
        self.assertFalse(os.path.exists(os.path.join(dst, "a.nii")))                # not even the non-conflicting file
        self.assertEqual(open(os.path.join(dst, "b.nii"), "rb").read(), b"ARCHIVED-B")
        self.assertEqual(self.job_files(rep["job_id"]), {"a.nii": "pending", "b.nii": "conflict", "c.nii": "skipped_identical"})

    def test_failure_while_staging_leaves_no_destination_change(self):
        src = self.tree("J3", {f"f{i}.nii": bytes([65 + i]) * 100 for i in range(5)})
        dst = os.path.join(self.E.base, "work", "J3_out", "deep")
        calls = {"n": 0}

        def boom(f):
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError(5, "simulated device error while staging")
        rep = self.svc.run(self.svc.submit("copy", [(src, dst)]), _hooks={"before_stage": boom})
        self.assertEqual(rep["state"], "failed")
        self.assertFalse(os.path.exists(os.path.join(self.E.base, "work", "J3_out")))   # no folder, no file, no .part
        self.assertIn("no destination was changed", rep["errors"][-1])

    def test_failure_while_committing_rolls_back_every_commit(self):
        src = self.tree("J4", {f"f{i}.nii": bytes([65 + i]) * 100 for i in range(4)})
        dst = self.tree("J4_out", {"f0.nii": b"OLD-0", "f1.nii": b"OLD-1"})
        before = {n: open(os.path.join(dst, n), "rb").read() for n in os.listdir(dst)}

        def boom(i, f):
            if i == 2:
                raise OSError(28, "simulated: no space left during commit")
        rep = self.svc.run(self.svc.submit("copy", [(src, dst)], mode="replace_after_verify"), _hooks={"before_commit": boom})
        self.assertEqual(rep["state"], "failed")
        self.assertIn("rolled back", rep["errors"][-1])
        self.assertEqual({n: open(os.path.join(dst, n), "rb").read() for n in os.listdir(dst)}, before)
        states = self.job_files(rep["job_id"])
        self.assertEqual(states["f0.nii"], "rolled_back")
        self.assertEqual(states["f3.nii"], "rolled_back")

    def test_destination_created_by_someone_else_during_commit(self):
        src = self.tree("J5", {"a.nii": b"MINE-A", "b.nii": b"MINE-B"})
        dst = os.path.join(self.E.vault, "studies", "J5")

        def racer(i, f):
            if i == 1:
                _w(os.path.join(dst, "b.nii"), b"SOMEONE-ELSE")                    # non-cooperating writer
        rep = self.svc.run(self.svc.submit("archive", [(src, dst)], study_id="J5"), _hooks={"before_commit": racer})
        self.assertEqual(rep["state"], "needs_attention")
        self.assertEqual(open(os.path.join(dst, "b.nii"), "rb").read(), b"SOMEONE-ELSE")   # never overwritten
        self.assertFalse(os.path.exists(os.path.join(dst, "a.nii")))                         # own commit rolled back

    def test_stage_preserves_previous_until_the_whole_job_is_verified(self):
        src = self.tree("J6", {"a.nii": b"FROM-VAULT-A", "b.nii": b"FROM-VAULT-B"})
        dst = self.tree("J6_ws", {"a.nii": b"LOCAL-A"})
        seen = {}

        def look(i, f):
            if i == 1:
                seen["preserved_during_job"] = os.path.exists(os.path.join(dst, f"a.nii.replaced-{job}"))
        job = self.svc.submit("stage", [(src, dst)], study_id="J6")
        rep = self.svc.run(job, _hooks={"before_commit": look})
        self.assertTrue(rep["ok"], rep)
        self.assertTrue(seen["preserved_during_job"])
        self.assertEqual(open(os.path.join(dst, "a.nii"), "rb").read(), b"FROM-VAULT-A")
        self.assertFalse(os.path.exists(os.path.join(dst, f"a.nii.replaced-{job}")))      # removed only at the end
        rep = self.svc.transfer("stage", [(self.tree("J6b", {"a.nii": b"V3"}), dst)], study_id="J6", keep_previous=True)
        self.assertEqual(len(rep["preserved_kept"]), 1)
        self.assertEqual(open(rep["preserved_kept"][0], "rb").read(), b"FROM-VAULT-A")
        os.remove(rep["preserved_kept"][0])

    def test_stale_replaced_file_is_never_overwritten(self):
        src = self.tree("J7", {"a.nii": b"NEW"})
        dst = self.tree("J7_ws", {"a.nii": b"OLD"})
        job = self.svc.submit("stage", [(src, dst)], study_id="J7")
        stale = _w(os.path.join(dst, f"a.nii.replaced-{job}"), b"EARLIER-PRESERVED")
        rep = self.svc.run(job)
        self.assertEqual(rep["state"], "failed")
        self.assertEqual(open(stale, "rb").read(), b"EARLIER-PRESERVED")
        self.assertEqual(open(os.path.join(dst, "a.nii"), "rb").read(), b"OLD")
        os.remove(stale)

    def test_vault_files_are_never_replaced(self):
        src = self.E.work("M01/a.nii", b"NEW")
        dst = _w(os.path.join(self.E.vault, "studies", "M01", "a.nii"), b"ARCHIVED")
        for mode in ("replace_after_verify", "preserve_previous"):
            with self.subTest(mode=mode):
                rep = self.svc.transfer("copy", [(src, dst)], mode=mode)
                self.assertFalse(rep["ok"])
                self.assertEqual(open(dst, "rb").read(), b"ARCHIVED")

    def test_move_removes_only_verified_unchanged_sources(self):
        src = self.tree("J8", {"a.nii": b"A", "b.nii": b"B", "sub/.DS_Store": b"F"})
        os.symlink(os.path.join(self.E.base, "raw", "M01"), os.path.join(src, "link"))
        dst = os.path.join(self.E.base, "work", "J8_moved")
        rep = self.svc.run(self.svc.submit("move", [(src, dst)]),
                           _hooks={"before_remove_sources": lambda: _w(os.path.join(src, "b.nii"), b"EDITED-AFTER-COPY")})
        self.assertEqual(rep["state"], "completed_with_retained_sources")
        self.assertFalse(os.path.exists(os.path.join(src, "a.nii")))
        self.assertEqual(open(os.path.join(src, "b.nii"), "rb").read(), b"EDITED-AFTER-COPY")   # changed -> kept
        self.assertTrue(os.path.islink(os.path.join(src, "link")))
        self.assertTrue(os.path.isfile(os.path.join(src, "sub", ".DS_Store")))
        self.assertEqual(open(os.path.join(dst, "b.nii"), "rb").read(), b"B")

    def test_pipeline_running_blocks_archive_and_stage(self):
        pats = os.path.join(self.E.base, "app_data", "patients.json")
        with open(pats, "w") as f:
            json.dump([{"code": "P1", "status": "running"}], f)
        try:
            src = self.tree("P1", {"a.nii": b"A"})
            for op, d in (("archive", os.path.join(self.E.vault, "studies", "P1")), ("stage", os.path.join(self.E.base, "work", "P1_ws"))):
                with self.subTest(op=op):
                    rep = self.svc.transfer(op, [(src, d)], study_id="P1")
                    self.assertEqual(rep["state"], "failed")
                    self.assertIn("being processed", rep["errors"][-1])
                    self.assertFalse(os.path.exists(d))
        finally:
            os.remove(pats)


# ================================================================================================ concurrency
CHILD = r"""
import os, sys, json, time
sys.path[:0] = %(path)r
from uengine.transfer import copier as CP
from uengine.safety import PathPolicy
pol = PathPolicy(%(base)r, %(vault)r)
while not os.path.exists(%(go)r):
    time.sleep(0.001)
try:
    r = CP.verified_copy(%(src)r, %(dst)r, policy=pol, job_tag=%(tag)r, mode=CP.CommitMode.NEVER_OVERWRITE)
    print(json.dumps({"status": r.status}))
except Exception as e:
    print(json.dumps({"status": "error", "error": repr(e)}))
"""


class TestConcurrency(Base):
    def test_cooperative_jobs_same_destination_threads(self):
        dst = os.path.join(self.E.vault, "studies", "C1", "a.nii")
        srcs = [self.E.work(f"C1/w{i}.nii", f"WRITER-{i}".encode()) for i in range(6)]
        results, barrier = [None] * 6, threading.Barrier(6)

        def run(i):
            svc = TransferService(self.E.base, self.E.vault)
            try:
                barrier.wait()
                results[i] = svc.transfer("archive", [(srcs[i], dst)], study_id="C1")
            finally:
                svc.close()
        ts = [threading.Thread(target=run, args=(i,)) for i in range(6)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        winners = [i for i, r in enumerate(results) if r["ok"]]
        self.assertEqual(len(winners), 1, [r["state"] for r in results])
        self.assertEqual(open(dst, "rb").read(), f"WRITER-{winners[0]}".encode())
        self.assertTrue(all(r["state"] == "needs_attention" for i, r in enumerate(results) if i not in winners))

    def test_uncoordinated_processes_race_on_the_atomic_commit(self):
        """8 processes WITHOUT locks commit different content to one name at the same instant: exactly one wins"""
        dst = os.path.join(self.E.vault, "studies", "C2", "race.nii")
        go = os.path.join(self.E.tmp, "go")
        procs = []
        for i in range(8):
            src = self.E.work(f"C2/p{i}.nii", f"PROC-{i}".encode() * 1000)
            code = CHILD % dict(path=CHILD_PATH, base=self.E.base, vault=self.E.vault, go=go, src=src, dst=dst, tag=f"proc{i}")
            procs.append(subprocess.Popen([PY, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        time.sleep(1.0)
        open(go, "w").close()
        out = [json.loads(p.communicate(timeout=120)[0].strip().splitlines()[-1]) for p in procs]
        self.assertEqual(sorted(o["status"] for o in out).count("committed"), 1, out)
        self.assertTrue(all(o["status"] in ("committed", "conflict") for o in out), out)
        winner = next(i for i, o in enumerate(out) if o["status"] == "committed")
        self.assertEqual(open(dst, "rb").read(), f"PROC-{winner}".encode() * 1000)
        self.assertEqual([n for n in os.listdir(os.path.dirname(dst)) if ".part-" in n], [])


# ================================================================================================ interrupted (killed) copies
KILL_CHILD = r"""
import os, sys, time
sys.path[:0] = %(path)r
from uengine.transfer import copier as CP
from uengine.transfer.service import TransferService
real = CP._hash_file
def slow(p, nocache=False, chunk=CP.CHUNK):
    if nocache and %(stage)r == "readback":
        print("STAGED", flush=True); time.sleep(120)
    return real(p, nocache, chunk)
CP._hash_file = slow
def hook(i, f):
    if %(stage)r == "commit" and i == 1:
        print("STAGED", flush=True); time.sleep(120)
svc = TransferService(%(base)r, %(vault)r)
job = svc.submit("archive", %(items)r, study_id="K1")
print("JOB " + job, flush=True)
svc.run(job, _hooks={"before_commit": hook})
"""


class TestKilledCopies(Base):
    def _kill_at(self, stage):
        src = self.tree("K1", {"a.nii": b"A" * 300000, "b.nii": b"B" * 300000})
        dst = os.path.join(self.E.vault, "studies", "K1")
        code = KILL_CHILD % dict(path=CHILD_PATH, base=self.E.base, vault=self.E.vault, stage=stage, items=[(src, dst)])
        p = subprocess.Popen([PY, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        job = None
        t0 = time.time()
        while time.time() - t0 < 60:
            line = p.stdout.readline()
            if line.startswith("JOB "):
                job = line.split()[1]
            if line.startswith("STAGED"):
                break
        os.kill(p.pid, signal.SIGKILL)
        p.wait(timeout=30)
        return job, dst

    def test_killed_while_staging_leaves_no_destination_file(self):
        job, dst = self._kill_at("readback")
        self.assertFalse(os.path.exists(os.path.join(dst, "a.nii")))
        self.assertFalse(os.path.exists(os.path.join(dst, "b.nii")))
        art = TR.list_stale_artifacts(dst)
        self.assertEqual([a["job"] for a in art], [job])                        # only the job-owned .part (for 1c)
        self.assertIn(self.svc.journal.get_job(job)["state"], ("copying", "flushing", "verifying"))
        for a in art:
            os.remove(a["path"])

    def test_killed_while_committing_is_recorded_exactly(self):
        job, dst = self._kill_at("commit")
        st = {f["rel_path"]: f["state"] for f in self.svc.journal.get_files(job)}
        self.assertEqual(self.svc.journal.get_job(job)["state"], "committing")
        self.assertEqual(st, {"a.nii": "committed", "b.nii": "verified"})       # the journal knows exactly what is where
        self.assertEqual(open(os.path.join(dst, "a.nii"), "rb").read(), b"A" * 300000)   # complete + verified, never partial
        self.assertFalse(os.path.exists(os.path.join(dst, "b.nii")))
        for a in TR.list_stale_artifacts(dst):
            os.remove(a["path"])


# ================================================================================================ callers
class TestCallers(Base):
    def test_file_manager_and_workspace_manager_use_verified_jobs(self):
        from uengine.file_manager import FileManager
        from uengine.study_workspace_manager import StudyWorkspaceManager
        fm = FileManager(self.E.base, self.E.vault)
        r = fm.copy_item(self.E.work("M01/a.nii", b"A"), os.path.join(self.E.base, "work"))
        self.assertTrue(r["ok"], r)
        self.assertIn("job_id", r)
        self.assertEqual(self.svc.journal.get_job(r["job_id"])["state"], "completed")
        swm = StudyWorkspaceManager(self.E.base, self.E.vault)
        _w(os.path.join(self.E.vault, "original_mri", "W1", "s.nii"), b"ORIG")
        swm.register_study("W1", os.path.join(self.E.vault, "original_mri", "W1"))
        ok, msg, _ = swm.stage_study("W1")
        self.assertTrue(ok, msg)
        ok, msg = swm.archive_study("W1")
        self.assertTrue(ok, msg)
        self.assertEqual(open(os.path.join(self.E.vault, "studies", "W1", "s.nii"), "rb").read(), b"ORIG")
        self.assertEqual(open(os.path.join(self.E.vault, "original_mri", "W1", "s.nii"), "rb").read(), b"ORIG")  # only read
        shutil.rmtree(os.path.join(self.E.vault, "original_mri", "W1"))         # remove the test's own fixture
        jobs = {j["operation"]: j["state"] for j in self.svc.journal.list_jobs()}
        self.assertEqual(jobs.get("stage"), "completed")
        self.assertEqual(jobs.get("archive"), "completed")

    def test_file_manager_archive_is_write_once(self):
        from uengine.file_manager import FileManager
        fm = FileManager(self.E.base, self.E.vault)
        _w(os.path.join(self.E.base, "review", "Q1_candidates.csv"), b"v1")     # synthetic study files in review/
        self.assertTrue(fm.archive_study("Q1")["ok"])
        with open(os.path.join(self.E.base, "review", "Q1_candidates.csv"), "wb") as f:
            f.write(b"v2 - re-detected")
        r = fm.archive_study("Q1")
        self.assertFalse(r["ok"])
        self.assertEqual(open(os.path.join(self.E.vault, "studies", "Q1", "Q1_candidates.csv"), "rb").read(), b"v1")
        os.remove(os.path.join(self.E.base, "review", "Q1_candidates.csv"))


if __name__ == "__main__":
    unittest.main()
