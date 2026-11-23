"""Phase 1e.1 tests: eject protection from real filesystem activity, read-only Vault verification.

Disk images are mounted INSIDE the temporary volumes root (PERCIVAL_VOLUMES_ROOT), so the eject manager sees real mount
points, real lsof results and real unmounts (the unmount runner calls `hdiutil detach` on the test's own image; diskutil
is never run). Synthetic data only."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_phase1a_transfer_core import Env, _w                         # noqa: E402
from test_phase1d_workers import big, wait                              # noqa: E402
from uengine.storage.eject_manager import EjectManager, _FORCE_TOKENS   # noqa: E402
from uengine.storage.models import DriveSafetyState                     # noqa: E402
from uengine.storage.storage_paths import StoragePathsService           # noqa: E402
from uengine.storage.vault_check import verify_vault                    # noqa: E402
from uengine.storage import activity as ACT                             # noqa: E402
from uengine.transfer.service import TransferRefused, TransferService    # noqa: E402
from uengine.transfer.workers import TransferWorkerPool                  # noqa: E402

VOLS = os.environ["PERCIVAL_VOLUMES_ROOT"]
TERMINAL = {"completed", "completed_with_retained_sources", "cancelled"}


def hdi(*a):
    return subprocess.run(["hdiutil", *a], capture_output=True, text=True)


class Images(unittest.TestCase):
    """APFS / HFS+ / FAT32 / exFAT images, each with a PERCIVAL_VAULT (manifest), mounted under the volumes root"""
    FS = {"apfs": "APFS", "hfs": "HFS+", "msdos": "MS-DOS FAT32", "exfat": "ExFAT", "ro": "APFS"}

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="p1e_img_")
        cls.imgs, cls.mounts = {}, {}
        if not shutil.which("hdiutil"):
            return
        for key, fs in cls.FS.items():
            img, mnt = os.path.join(cls.dir, f"{key}.dmg"), os.path.join(VOLS, f"P1E{key.upper()}")
            os.makedirs(mnt, exist_ok=True)
            if hdi("create", "-quiet", "-size", "48m", "-fs", fs, "-volname", f"P1E{key}", img).returncode:
                continue
            cls.imgs[key] = img
            if not cls.attach(key):
                continue
            v = os.path.join(mnt, "PERCIVAL_VAULT")
            _w(os.path.join(v, "manifest", "vault_manifest.json"), json.dumps({"vault_id": key}).encode())
            os.makedirs(os.path.join(v, "studies"), exist_ok=True)
            if key == "ro":                                                    # re-attach read-only
                hdi("detach", "-quiet", mnt)
                if not cls.attach(key, "-readonly"):
                    continue
            cls.mounts[key] = mnt

    @classmethod
    def attach(cls, key, *extra):
        mnt = os.path.join(VOLS, f"P1E{key.upper()}")
        hdi("attach", "-quiet", "-nobrowse", "-noverify", *extra, "-mountpoint", mnt, cls.imgs[key])
        return os.path.ismount(mnt)

    @classmethod
    def tearDownClass(cls):
        for mnt in [os.path.join(VOLS, f"P1E{k.upper()}") for k in cls.FS]:
            for extra in ([], ["-force"]):
                if os.path.ismount(mnt):
                    hdi("detach", "-quiet", *extra, mnt)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def mnt(self, key):
        if key not in self.mounts or not os.path.ismount(self.mounts[key]):
            self.skipTest(f"{key} image unavailable")
        return self.mounts[key]

    def vault(self, key):
        return os.path.join(self.mnt(key), "PERCIVAL_VAULT")

    def setUp(self):
        self.E = Env()
        self._env = mock.patch.dict(os.environ, {})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.E.assert_protected_intact(self)
        self.E.close()


# ================================================================================================ vault verification
class TestVaultCheck(Images):
    def test_verdicts_per_filesystem(self):
        for key, verdict in (("apfs", "archive_ok"), ("hfs", "archive_ok"), ("msdos", "archive_ok"), ("exfat", "read_only"),
                             ("ro", "read_only")):
            with self.subTest(fs=key):
                before = sorted(os.listdir(self.vault(key)))
                v = verify_vault(self.vault(key))
                self.assertEqual(v["verdict"], verdict, v)
                self.assertEqual(v["can_archive_to"], verdict == "archive_ok")
                self.assertTrue(v["can_stage_from"])
                self.assertEqual(v["mount_point"], os.path.realpath(self.mnt(key)))
                self.assertEqual(sorted(os.listdir(self.vault(key))), before)       # never writes
        self.assertEqual(verify_vault(self.vault("exfat"))["filesystem"], "exfat")
        self.assertTrue(verify_vault(self.vault("ro"))["read_only"])

    def test_not_a_vault_unavailable_and_internal(self):
        plain = os.path.join(self.mnt("apfs"), "just_a_folder")
        os.makedirs(plain, exist_ok=True)
        self.assertEqual(verify_vault(plain)["verdict"], "not_a_vault")
        self.assertEqual(verify_vault(os.path.join(self.mnt("apfs"), "missing"))["verdict"], "unavailable")
        self.assertEqual(verify_vault("relative/path")["verdict"], "unavailable")
        internal = os.path.join(self.E.tmp, "internal_vault")
        _w(os.path.join(internal, "manifest", "vault_manifest.json"), b"{}")
        v = verify_vault(internal)
        self.assertEqual(v["verdict"], "not_external")
        self.assertFalse(v["can_archive_to"])
        _w(os.path.join(plain, "manifest", "vault_manifest.json"), b"{not json")
        self.assertEqual(verify_vault(plain)["verdict"], "not_a_vault")
        shutil.rmtree(plain)

    def test_read_only_and_exfat_destinations_are_refused_before_writing(self):
        for key, word in (("ro", "read-only"), ("exfat", "exfat")):
            with self.subTest(fs=key):
                svc = TransferService(self.E.base, self.vault(key))
                try:
                    with self.assertRaises(TransferRefused) as cm:
                        svc.transfer("archive", [(self.E.work("M01/a.nii", b"a"), os.path.join(self.vault(key), "studies", "M01"))])
                    self.assertIn(word, str(cm.exception))
                finally:
                    svc.close()

    def test_endpoint(self):
        from uengine.transfer import api
        pool = TransferWorkerPool(self.E.base, self.vault("apfs"), poll_s=0.05).start()
        try:
            self.assertEqual(api.handle_get("vault_check", {}, pool)["vault"]["verdict"], "archive_ok")
            self.assertEqual(api.handle_get("vault_check", {"path": self.vault("exfat")}, pool)["vault"]["verdict"], "read_only")
        finally:
            pool.shutdown(5)
            pool.close()


# ================================================================================================ eject protection
class TestEjectProtection(Images):
    def em(self, key, runner=None, lsof_runner=None):
        return EjectManager(StoragePathsService(self.E.base, self.vault(key)), runner=runner, lsof_runner=lsof_runner)

    def detach_runner(self, calls):
        def run(cmd):
            calls.append(list(cmd))
            r = hdi("detach", *(["-force"] if "force" in cmd else []), cmd[-1])
            return types.SimpleNamespace(returncode=r.returncode, stdout=r.stdout, stderr=r.stderr)
        return run

    def test_idle_drive_is_ready(self):
        c = self.em("hfs").check_ejection_safety()
        self.assertEqual(c.state, DriveSafetyState.READY, c.to_dict())
        self.assertTrue(c.can_eject)

    def test_open_file_on_the_drive_blocks(self):
        p = _w(os.path.join(self.vault("hfs"), "studies", "held.nii"), b"x")
        with open(p, "rb"):
            c = self.em("hfs").check_ejection_safety()
            self.assertEqual(c.state, DriveSafetyState.BUSY, c.to_dict())
            self.assertFalse(c.can_eject)
            self.assertIn(os.getpid(), [h["pid"] for h in c.details["open_handles"]])
            r = self.em("hfs", runner=lambda cmd: self.fail("must not unmount")).eject_vault()
            self.assertFalse(r["ok"])
        self.assertTrue(self.em("hfs").check_ejection_safety().can_eject)
        os.remove(p)

    def test_unknown_activity_is_never_treated_as_safe(self):
        for runner in (lambda cmd: (_ for _ in ()).throw(OSError(2, "lsof missing")),
                       lambda cmd: types.SimpleNamespace(returncode=2, stdout="", stderr="lsof: permission denied")):
            c = self.em("hfs", lsof_runner=runner).check_ejection_safety()
            self.assertEqual(c.state, DriveSafetyState.UNKNOWN)
            self.assertFalse(c.can_eject)

    def test_active_transfer_blocks_every_kind_of_eject_then_emergency_pauses_it(self):
        vault = self.vault("apfs")
        src = big(os.path.join(self.E.base, "work", "EJ", "x.nii"), 24)
        pool = TransferWorkerPool(self.E.base, vault, poll_s=0.05).start()
        svc = TransferService(self.E.base, vault)
        calls = []
        try:
            os.environ["PERCIVAL_TEST_SLOW_AT"] = "copy.chunk=0.1"
            job = pool.submit("archive", [(os.path.dirname(src), os.path.join(vault, "studies", "EJ"))], study_id="EJ")["job_id"]
            wait(lambda: svc.journal.get_job(job)["state"] == "copying", what="copying")
            c = self.em("apfs").check_ejection_safety()
            self.assertEqual(c.state, DriveSafetyState.TRANSFERRING, c.to_dict())
            self.assertIn(job, c.active_job_ids)
            self.assertFalse(self.em("apfs", runner=self.detach_runner(calls)).eject_vault()["ok"])
            # a force authorisation does not help while protected operations run
            tok = EjectManager._issue_force_token(os.path.realpath(self.mnt("apfs")), "P1EAPFS")
            r = self.em("apfs", runner=self.detach_runner(calls)).eject_vault(force=True, force_token=tok,
                                                                             confirm_volume_name="P1EAPFS")
            self.assertFalse(r["ok"])
            self.assertEqual(svc.journal.get_job(job)["state"], "copying")       # untouched by a refused eject
            self.assertEqual(calls, [])
            self.assertIn("transfer job", r.get("error", "") + json.dumps(r))
            # emergency eject: the job is asked to pause at a safe boundary, then the drive is unmounted
            r = self.em("apfs", runner=self.detach_runner(calls)).eject_vault(emergency=True)
            self.assertEqual(svc.journal.get_job(job)["state"], "paused")
            if not r["ok"]:                                                    # macOS refused (e.g. indexer): force flow
                self.assertTrue(r.get("needs_force_confirmation"), r)
                r = self.em("apfs", runner=self.detach_runner(calls)).eject_vault(
                    emergency=True, force=True, force_token=r["force_token"], confirm_volume_name=r["volume_name"])
            self.assertTrue(r["ok"], r)
            self.assertFalse(os.path.ismount(os.path.join(VOLS, "P1EAPFS")))
            os.environ.pop("PERCIVAL_TEST_SLOW_AT")
            # the paused job resumes once the drive is back
            self.assertTrue(self.attach("apfs"))
            pool.resume(job)
            wait(lambda: svc.journal.get_job(job)["state"] in TERMINAL, what="resumed")
            self.assertEqual(os.path.getsize(os.path.join(vault, "studies", "EJ", "x.nii")), os.path.getsize(src))
        finally:
            pool.shutdown(5)
            pool.close()
            svc.close()
            if not os.path.ismount(os.path.join(VOLS, "P1EAPFS")):
                self.attach("apfs")

    def test_paused_job_does_not_block_but_is_reported(self):
        vault = self.vault("hfs")
        src = os.path.dirname(big(os.path.join(self.E.base, "work", "PJ", "x.nii"), 16))
        pool = TransferWorkerPool(self.E.base, vault, poll_s=0.05).start()
        svc = TransferService(self.E.base, vault)
        try:
            os.environ["PERCIVAL_TEST_SLOW_AT"] = "copy.chunk=0.1"
            job = pool.submit("archive", [(src, os.path.join(vault, "studies", "PJ"))], study_id="PJ")["job_id"]
            wait(lambda: svc.journal.get_job(job)["state"] == "copying", what="copying")
            pool.pause(job)
            wait(lambda: svc.journal.get_job(job)["state"] == "paused", what="paused")
            c = self.em("hfs").check_ejection_safety()
            self.assertTrue(c.can_eject, c.to_dict())
            self.assertEqual([j["job_id"] for j in c.details["parked_jobs"]], [job])
            self.assertIn("will need this drive", c.reason)
            os.environ.pop("PERCIVAL_TEST_SLOW_AT")
            pool.discard(job)
            wait(lambda: svc.journal.get_job(job)["state"] in TERMINAL, what="discarded")
        finally:
            pool.shutdown(5)
            pool.close()
            svc.close()

    def test_journal_is_read_only_for_the_check(self):
        jdb = os.path.join(self.E.base, "app_data", "transfers", "journal.db")
        self.assertFalse(os.path.exists(jdb))
        self.em("hfs").check_ejection_safety()
        self.assertFalse(os.path.exists(jdb))                                   # never created by an eject check
        self.assertEqual(ACT.journal_activity(self.E.base, self.mnt("hfs"))["journal"], "absent")


if __name__ == "__main__":
    unittest.main()
