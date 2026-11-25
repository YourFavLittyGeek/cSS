"""2026-11-25 Pensieve move: after the final review a study's processed files move to the Pensieve drive (real exFAT image),
the Mac copy is deleted only after SHA-256 verification, and the study comes back on demand (missing files only, verified)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
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
sys.path[:0] = [os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine")]
import pensieve_move as PM                                                   # noqa: E402

VOLS = os.environ["PERCIVAL_VOLUMES_ROOT"]
CODE = "Study-077"


def _w(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return p


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


STUDY_FILES = {
    f"raw/{CODE}/SWI/15_SWI.nii.gz": b"RAW-SWI" * 1000, f"raw/{CODE}/SWI/15_SWI.json": b"{}",
    f"raw/{CODE}/T1/3_T1.nii.gz": b"RAW-T1" * 800,
    f"data/{CODE}_swi.nii": b"SKULLSTRIPPED" * 900, f"data/{CODE}_t1.nii.gz": b"T1" * 50,
    f"work/{CODE}_dark.nii.gz": b"DARK" * 300, f"work/{CODE}_seg_swispace.nii.gz": b"SEG" * 300,
    f"synthseg/{CODE}_seg.nii.gz": b"SYNTHSEG", f"logs/{CODE}_run.log": b"log text",
    f"subjects/{CODE}/mri/aparc+aseg.mgz": b"MGZ" * 100,
}
REVIEW_FILES = {f"review/{CODE}_candidates.csv": b"cand_id\n1\n", f"review/{CODE}_candidates.nii.gz": b"LAB",
                f"review/{CODE}_calls_Reader_A.csv": b"cand_id,call\n1,cSS\n"}
OTHER = {"raw/Study-0770/SWI/x.nii.gz": b"OTHER STUDY", "data/Study-0770_swi.nii": b"OTHER", "work/Study-07_dark.nii.gz": b"OTHER"}


class _ExfatImage(unittest.TestCase):
    """one exFAT disk image with a PERCIVAL_VAULT, mounted under the test volumes root"""
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pmove_")
        cls.mnt = os.path.join(VOLS, "PMOVEEXFAT")
        os.makedirs(cls.mnt, exist_ok=True)
        img = os.path.join(cls.dir, "x.dmg")
        cls.ok = (shutil.which("hdiutil") and
                  subprocess.run(["hdiutil", "create", "-quiet", "-size", "48m", "-fs", "ExFAT", "-volname", "PMOVE", img], capture_output=True).returncode == 0 and
                  subprocess.run(["hdiutil", "attach", "-quiet", "-nobrowse", "-noverify", "-mountpoint", cls.mnt, img], capture_output=True).returncode == 0)
        cls.vault = os.path.join(cls.mnt, "PERCIVAL_VAULT")
        if cls.ok:
            _w(os.path.join(cls.vault, "manifest", "vault_manifest.json"), b'{"vault_id": "t"}')
            os.makedirs(os.path.join(cls.vault, "studies"), exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        for extra in ([], ["-force"]):
            if os.path.ismount(cls.mnt):
                subprocess.run(["hdiutil", "detach", "-quiet", *extra, cls.mnt], capture_output=True)
        shutil.rmtree(cls.dir, ignore_errors=True)


class TestPensieveMove(_ExfatImage):
    def setUp(self):
        if not self.ok:
            self.skipTest("exFAT disk image unavailable")
        self.B = tempfile.mkdtemp(prefix="pmove_proj_", dir=self.dir)
        for d in ("app_data", "review", "raw", "data", "work"):
            os.makedirs(os.path.join(self.B, d), exist_ok=True)
        for rel, data in {**STUDY_FILES, **REVIEW_FILES, **OTHER}.items():
            _w(os.path.join(self.B, rel), data)
        t = time.time() - 3600                                                   # the reading itself happened an hour ago
        for rel in REVIEW_FILES:
            os.utime(os.path.join(self.B, rel), (t, t))
        PM.STATUS.clear()

    def tearDown(self):
        for rel, data in OTHER.items():                                         # other studies are never touched
            self.assertEqual(open(os.path.join(self.B, rel), "rb").read(), data, rel)

    def final(self, age_s=600):
        p = _w(os.path.join(self.B, "review", f"{CODE}_final_Reader_A.json"), b'{"saved": "x"}')
        t = time.time() - age_s
        os.utime(p, (t, t))
        return p

    def test_drive_is_ready_on_exfat(self):
        self.assertEqual(PM.drive_ready(self.vault), (True, ""))
        self.assertFalse(PM.drive_ready(os.path.join(VOLS, "missing", "PERCIVAL_VAULT"))[0])

    def test_due_needs_done_final_and_grace(self):
        p = dict(code=CODE, status="done")
        self.assertFalse(PM.due(self.B, p))                                      # no final review yet
        self.final(age_s=30)
        self.assertFalse(PM.due(self.B, p, grace_s=300))                         # just saved: the reviewer may still be there
        self.final(age_s=600)
        self.assertTrue(PM.due(self.B, p, grace_s=300))
        self.assertFalse(PM.due(self.B, dict(code=CODE, status="running"), grace_s=300))

    def test_reviews_saved_before_the_update_do_not_move_by_themselves(self):
        fin = os.path.getmtime(self.final(age_s=3600))
        p = dict(code=CODE, status="done")
        self.assertFalse(PM.due(self.B, p, grace_s=300, since=fin + 10))         # feature switched on after this review
        self.assertTrue(PM.due(self.B, p, grace_s=300, since=fin - 10))          # reviewed after the switch-on
        self.assertTrue(PM.due(self.B, p, grace_s=300, since=0))                 # "Move earlier reviewed studies now"

    def test_move_verifies_then_deletes_and_restore_brings_back(self):
        self.final()
        before = {rel: _sha(os.path.join(self.B, rel)) for rel in STUDY_FILES}
        r = PM.move(self.B, self.vault, CODE)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["files"], len(STUDY_FILES))
        m = PM.read_marker(self.B, CODE)
        self.assertEqual(m["state"], "in_pensieve")
        root = os.path.join(self.vault, m["vault_rel"])
        for rel, sha in before.items():
            self.assertFalse(os.path.exists(os.path.join(self.B, rel)), rel)                  # gone from the Mac
            self.assertEqual(_sha(os.path.join(root, rel)), sha, rel)                         # identical on Pensieve
        self.assertFalse(os.path.exists(os.path.join(self.B, "raw", CODE)))                   # empty folders removed
        for rel, data in REVIEW_FILES.items():                                                # review files: copied AND kept
            self.assertEqual(open(os.path.join(self.B, rel), "rb").read(), data)
            self.assertTrue(os.path.isfile(os.path.join(root, rel)))
        self.assertTrue(os.path.isfile(os.path.join(root, "pensieve_manifest.json")))
        self.assertTrue(PM.in_pensieve(self.B, CODE))
        self.assertFalse(PM.due(self.B, dict(code=CODE, status="done"), grace_s=0))           # not moved twice

        r2 = PM.restore(self.B, self.vault, CODE)
        self.assertTrue(r2["ok"], r2)
        self.assertEqual(r2["restored"], len(STUDY_FILES))
        for rel, sha in before.items():
            self.assertEqual(_sha(os.path.join(self.B, rel)), sha, rel)
        self.assertEqual(PM.read_marker(self.B, CODE)["state"], "on_mac")
        self.assertEqual(sorted(os.listdir(root)), sorted(set(["pensieve_manifest.json"] + [r.split("/")[0] for r in {**STUDY_FILES, **REVIEW_FILES}])))

    def test_re_review_archives_a_new_version_and_keeps_the_old_one(self):
        self.final(age_s=900)
        self.assertTrue(PM.move(self.B, self.vault, CODE)["ok"])
        v1 = PM.read_marker(self.B, CODE)["version"]
        self.assertTrue(PM.restore(self.B, self.vault, CODE)["ok"])
        self.assertFalse(PM.due(self.B, dict(code=CODE, status="done"), grace_s=0))           # restored, not reviewed again
        time.sleep(1.1)
        self.final(age_s=0)
        _w(os.path.join(self.B, "review", f"{CODE}_calls_Reader_A.csv"), b"cand_id,call\n1,Vessel\n")
        self.assertTrue(PM.due(self.B, dict(code=CODE, status="done"), grace_s=0))
        r = PM.move(self.B, self.vault, CODE)
        self.assertTrue(r["ok"], r)
        m = PM.read_marker(self.B, CODE)
        self.assertNotEqual(m["version"], v1)
        self.assertEqual(m["versions"], [v1, m["version"]])
        old = os.path.join(self.vault, "studies", CODE, v1, "review", f"{CODE}_calls_Reader_A.csv")
        self.assertEqual(open(old, "rb").read(), REVIEW_FILES[f"review/{CODE}_calls_Reader_A.csv"])    # first version untouched

    def test_a_crash_while_deleting_leaves_a_restorable_record(self):
        self.final()
        real = os.remove; n = {"k": 0}
        def dying_remove(p):
            n["k"] += 1
            if n["k"] == 3: raise KeyboardInterrupt("app killed while deleting")
            real(p)
        with mock.patch.object(PM.os, "remove", side_effect=dying_remove):
            with self.assertRaises(KeyboardInterrupt):
                PM.move(self.B, self.vault, CODE)
        PM.STATUS.clear()
        self.assertEqual(PM.read_marker(self.B, CODE)["state"], "deleting")
        self.assertTrue(PM.in_pensieve(self.B, CODE))
        self.assertEqual(PM.state(self.B, CODE), "in_pensieve")
        r = PM.restore(self.B, self.vault, CODE)
        self.assertTrue(r["ok"], r)
        for rel, data in STUDY_FILES.items():
            self.assertEqual(open(os.path.join(self.B, rel), "rb").read(), data, rel)

    def test_recent_reading_activity_postpones_the_move(self):
        self.final(age_s=900)
        _w(os.path.join(self.B, "review", f"{CODE}_events_Reader_A.jsonl"), b"{}\n")      # a decision just now
        self.assertFalse(PM.due(self.B, dict(code=CODE, status="done"), grace_s=300))
        t = time.time() - 900
        for q in os.listdir(os.path.join(self.B, "review")):
            os.utime(os.path.join(self.B, "review", q), (t, t))
        self.assertTrue(PM.due(self.B, dict(code=CODE, status="done"), grace_s=300))

    def test_archive_copies_are_write_once_and_dicom_copies_never_move(self):
        self.final()
        dic = _w(os.path.join(self.B, "raw", CODE, "SWI", "_dicom", "IM0001.dcm"), b"DICOM-TEMP")
        self.assertTrue(PM.move(self.B, self.vault, CODE)["ok"])
        root = os.path.join(self.vault, PM.read_marker(self.B, CODE)["vault_rel"])
        self.assertFalse(os.path.exists(os.path.join(root, "raw", CODE, "SWI", "_dicom")))     # not archived
        self.assertTrue(os.path.exists(dic))                                                 # left for source_cleanup
        from uengine.safety import PathPolicy, SafetyError
        pol = PathPolicy(self.B, self.vault)
        for target in (root, os.path.join(root, f"data/{CODE}_swi.nii"), os.path.join(self.vault, "studies", CODE)):
            with self.assertRaises(SafetyError, msg=target):
                pol.check_modify(target)                                                     # File Manager delete / move / rename
        pol.check_write_target(os.path.join(self.vault, "studies", CODE, "r_new", "x.nii"))  # a new version can still be written
        import source_cleanup as SRC
        self.assertTrue(SRC.has_nifti(self.B, CODE, "SWI"))                                  # moved, recorded -> still "converted"

    def test_copy_only_keeps_the_mac_files(self):
        self.final()
        r = PM.move(self.B, self.vault, CODE, delete_local=False)
        self.assertTrue(r["ok"], r)
        self.assertEqual(PM.read_marker(self.B, CODE)["state"], "copied")
        for rel in STUDY_FILES:
            self.assertTrue(os.path.exists(os.path.join(self.B, rel)))

    def test_a_file_that_does_not_verify_stays_on_the_mac(self):
        self.final()
        real = PM._sha
        bad = os.path.join(self.B, f"work/{CODE}_dark.nii.gz")
        with mock.patch.object(PM, "_sha", side_effect=lambda p: "0" * 64 if p.startswith(self.vault) and p.endswith(f"{CODE}_dark.nii.gz") else real(p)):
            r = PM.move(self.B, self.vault, CODE)
        self.assertTrue(r["ok"], r)
        self.assertEqual([k["rel"] for k in r["kept_local"]], [f"work/{CODE}_dark.nii.gz"])
        self.assertTrue(os.path.exists(bad))                                                  # not verified -> not deleted
        self.assertFalse(os.path.exists(os.path.join(self.B, f"data/{CODE}_swi.nii")))

    def test_drive_missing_nothing_is_deleted(self):
        self.final()
        r = PM.move(self.B, os.path.join(VOLS, "NOPE", "PERCIVAL_VAULT"), CODE)
        self.assertFalse(r["ok"])
        for rel in STUDY_FILES:
            self.assertTrue(os.path.exists(os.path.join(self.B, rel)))

    def test_restore_without_drive_asks_for_it(self):
        self.final()
        self.assertTrue(PM.move(self.B, self.vault, CODE)["ok"])
        r = PM.restore(self.B, os.path.join(VOLS, "NOPE", "PERCIVAL_VAULT"), CODE)
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("need_drive"))
        self.assertEqual(PM.read_marker(self.B, CODE)["state"], "in_pensieve")

    def test_restore_never_overwrites_a_file_already_on_the_mac(self):
        self.final()
        self.assertTrue(PM.move(self.B, self.vault, CODE)["ok"])
        _w(os.path.join(self.B, f"data/{CODE}_swi.nii"), b"SOMETHING NEW")
        r = PM.restore(self.B, self.vault, CODE)
        self.assertFalse(r["ok"])                                                             # does not match the record
        self.assertEqual(open(os.path.join(self.B, f"data/{CODE}_swi.nii"), "rb").read(), b"SOMETHING NEW")

    def test_restore_policy_opens_only_this_studys_missing_files(self):
        pol = PM._restore_policy(self.B, self.vault, CODE)
        from uengine.safety import SafetyError
        pol.check_write_target(os.path.join(self.B, "raw", CODE, "SWI", "new.nii.gz"))
        pol.check_write_target(os.path.join(self.B, "data", f"{CODE}_flair.nii.gz"))
        for p in (os.path.join(self.B, "data", "Study-0770_swi.nii"),                       # another study
                  os.path.join(self.B, "raw", "Study-0770", "SWI", "y.nii.gz"),
                  os.path.join(self.B, f"raw/{CODE}/SWI/15_SWI.nii.gz"),                    # exists -> still protected
                  os.path.join(self.B, "review", f"{CODE}_x.csv")):
            with self.assertRaises(SafetyError, msg=p):
                pol.check_write_target(p)


class TestReviewerBringsTheStudyBack(_ExfatImage):
    """the reviewer starts with a study in Pensieve, the page asks for it, it comes back verified and opens"""
    def setUp(self):
        if not self.ok:
            self.skipTest("exFAT disk image unavailable")
        PM.STATUS.clear()
        from test_phase3a2_blind import build
        self.B = tempfile.mkdtemp(prefix="pmove_rv_", dir=os.environ["CSS_BASE"])
        build(self.B)
        _w(os.path.join(self.B, "app_data", "settings.json"), json.dumps(dict(vault_mount=self.vault)).encode())
        _w(os.path.join(self.B, "review", "S1_final_Reader_A.json"), b"{}")
        self.swi = _sha(os.path.join(self.B, "data", "S1_swi.nii"))

    def test_open_restore_and_load(self):
        from test_phase3a2_blind import Server
        self.assertTrue(PM.move(self.B, self.vault, "S1")["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.B, "data", "S1_swi.nii")))
        srv = Server(self.B)                                    # starts although the SWI is not on the Mac
        try:
            m = srv.get("/api/meta?study=S1&reviewer=Reader%20A")
            self.assertTrue(m.get("in_pensieve"), m)
            self.assertTrue(srv.get("/api/vol?study=S1&seq=swi").get("in_pensieve"))
            self.assertIn("error", srv.post("/api/pensieve_restore", dict(study="NOT_HERE")))
            self.assertTrue(srv.post("/api/pensieve_restore", dict(study="S1"))["ok"])
            for _ in range(120):
                st = srv.get("/api/pensieve?study=S1")
                if not st["away"] and st["state"] != "restoring":
                    break
                time.sleep(0.25)
            self.assertEqual(st["state"], "on_mac", st)
            self.assertEqual(_sha(os.path.join(self.B, "data", "S1_swi.nii")), self.swi)
            m2 = srv.get("/api/meta?study=S1&reviewer=Reader%20A")
            self.assertNotIn("in_pensieve", m2)
            self.assertIn("shape", m2)
        finally:
            srv.stop()

    def test_drive_unplugged_the_page_gets_a_clear_answer(self):
        from test_phase3a2_blind import Server
        self.assertTrue(PM.move(self.B, self.vault, "S1")["ok"])
        _w(os.path.join(self.B, "app_data", "settings.json"), json.dumps(dict(vault_mount=os.path.join(VOLS, "GONE", "PERCIVAL_VAULT"))).encode())
        srv = Server(self.B)
        try:
            srv.post("/api/pensieve_restore", dict(study="S1"))
            for _ in range(60):
                st = srv.get("/api/pensieve?study=S1")
                if st["state"] == "failed":
                    break
                time.sleep(0.25)
            self.assertEqual(st["state"], "failed")
            self.assertIn("connect the Pensieve drive", st["error"])
        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main()
