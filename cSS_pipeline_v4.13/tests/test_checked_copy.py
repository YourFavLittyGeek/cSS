"""2026-11-25 audit items 9 + 10.
9: the import copy and the Vault backup use uengine/transfer/checked_copy.py (temporary name, read back, SHA-256 compared, then renamed;
   never a half-written or unverified file under the final name; a backup folder gets its name only when every file matched).
10: when the Mac is below the low-space limit, the app offers to move the reviewed studies still on the Mac (and the 'free space' run
   moves them even when the automatic move would not). Temporary folders only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)
from uengine.transfer import checked_copy as CC   # noqa: E402


def w(p, b):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f: f.write(b)


def leftovers(d): return [os.path.join(r, f) for r, ds, fs in os.walk(d) for f in fs + ds if ".part-" in f or f.endswith(".partial")]


class TestCheckedCopy(unittest.TestCase):
    def setUp(self): self.T = tempfile.mkdtemp(prefix="checked_copy_")

    def test_copy_identical_conflict_replace(self):
        a = os.path.join(self.T, "src", "a.dcm"); w(a, b"abc" * 1000); d = os.path.join(self.T, "dst", "x", "a.dcm")
        r = CC.copy_file(a, d)
        self.assertEqual(r["status"], "copied"); self.assertEqual(r["sha256"], hashlib.sha256(b"abc" * 1000).hexdigest())
        self.assertEqual(open(d, "rb").read(), b"abc" * 1000)
        self.assertEqual(CC.copy_file(a, d)["status"], "identical")
        w(a, b"changed")
        with self.assertRaises(CC.CheckedCopyError): CC.copy_file(a, d)               # a different file is never overwritten ...
        self.assertEqual(open(d, "rb").read(), b"abc" * 1000)
        self.assertEqual(CC.copy_file(a, d, replace=True)["status"], "replaced")      # ... unless asked (import copy), after verification
        self.assertEqual(open(d, "rb").read(), b"changed")
        self.assertEqual(leftovers(self.T), [])

    def test_mismatch_leaves_nothing_under_the_final_name(self):
        a = os.path.join(self.T, "src", "a.dcm"); w(a, b"data" * 100); d = os.path.join(self.T, "dst", "a.dcm")
        real = CC._hash_file
        with mock.patch.object(CC, "_hash_file", side_effect=lambda p, nocache=False: ("0" * 64, True) if ".part-" in p else real(p, nocache)), \
             mock.patch.object(CC, "_clone", return_value=False):
            with self.assertRaises(CC.CheckedCopyError): CC.copy_file(a, d)
        self.assertFalse(os.path.exists(d)); self.assertEqual(leftovers(self.T), [])

    def test_tree_is_all_or_nothing(self):
        s = os.path.join(self.T, "tree"); w(os.path.join(s, "x", "1.bin"), b"1"); w(os.path.join(s, "y", "2.bin"), b"22")
        os.symlink(os.path.join(s, "x", "1.bin"), os.path.join(s, "link.bin"))
        r = CC.copy_tree(s, os.path.join(self.T, "out"))
        self.assertEqual(sorted(f["rel"] for f in r["files"]), ["x/1.bin", "y/2.bin"])   # links are not followed
        real = CC.copy_file
        def boom(a, b, **k):
            if a.endswith("2.bin"): raise CC.CheckedCopyError("simulated mismatch")
            return real(a, b, **k)
        with mock.patch.object(CC, "copy_file", side_effect=boom):
            with self.assertRaises(CC.CheckedCopyError): CC.copy_tree(s, os.path.join(self.T, "out2"))
        self.assertFalse(os.path.exists(os.path.join(self.T, "out2"))); self.assertEqual(leftovers(self.T), [])

    def test_vault_backup_is_verified_and_named_only_when_complete(self):
        from uengine.vault import PercivalDataVault
        v = object.__new__(PercivalDataVault)
        v.root_path = os.path.join(self.T, "VAULT"); v._is_connected = True; v._manifest = {"vault_id": "V1"}
        w(os.path.join(v.root_path, "manifest", "vault_manifest.json"), b"{}")
        w(os.path.join(v.root_path, "PENSIEVE", "Database_Backups", "b.db"), b"db" * 500)
        w(os.path.join(v.root_path, "models", "m.json"), b"{}")
        dest = os.path.join(self.T, "backups")
        ok, msg = v.create_backup(dest); self.assertTrue(ok, msg)
        (name,) = os.listdir(dest); m = json.load(open(os.path.join(dest, name, "backup_manifest.json")))
        self.assertEqual(m["n_files"], 3)
        for f in m["files"]:
            self.assertEqual(hashlib.sha256(open(os.path.join(dest, name, f["rel"]), "rb").read()).hexdigest(), f["sha256"])
        self.assertFalse(v.create_backup(os.path.join(v.root_path, "inside"))[0])        # never into the Vault itself
        with mock.patch.object(CC, "copy_file", side_effect=CC.CheckedCopyError("simulated mismatch")):
            ok, msg = v.create_backup(os.path.join(self.T, "backups2"))
        self.assertFalse(ok); self.assertIn("nothing kept", msg)
        self.assertEqual(os.listdir(os.path.join(self.T, "backups2")), [])

    def test_import_copy_is_verified(self):
        import import_wizard as IW
        s = os.path.join(self.T, "ext", "SWI"); [w(os.path.join(s, f"im{i}"), bytes([i]) * 50) for i in range(3)]
        n = os.path.join(self.T, "ext", "t1.nii.gz"); w(n, b"nii"); w(os.path.join(self.T, "ext", "t1.json"), b"{}")
        root = os.path.join(self.T, "app_data", "import_src")
        out = IW._neutral_copy({"SWI": s, "T1": n}, "K1", root)
        self.assertEqual(sorted(os.listdir(out["SWI"])), ["SWI_00000.dcm", "SWI_00001.dcm", "SWI_00002.dcm"])
        self.assertTrue(os.path.exists(os.path.join(root, "K1", "T1_series.json")))
        with mock.patch.object(CC, "_hash_file", return_value=("0" * 64, True)), mock.patch.object(CC, "_clone", return_value=False):
            with self.assertRaises(CC.CheckedCopyError): IW._neutral_copy({"T1": n}, "K2", root)   # a failed check stops the import
        self.assertFalse(os.path.exists(os.path.join(root, "K2", "T1_series.nii.gz")))


class TestLowSpace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import css_app
        cls.app = css_app

    def test_offer_only_below_the_limit_and_only_studies_not_moving_by_themselves(self):
        A = self.app; import pensieve_move as PMV
        B = A.B; w(os.path.join(B, "raw", "LS1", "SWI", "a.nii"), b"x" * 2000)
        pats = [dict(code="LS1", status="done"), dict(code="LS2", status="done")]
        due = lambda B_, p, g=0, since=0.0, **k: p["code"] == "LS1" or (p["code"] == "LS2" and not since)   # LS2 moves by itself
        Usage = lambda free: mock.patch.object(A.shutil, "disk_usage", return_value=mock.Mock(free=free * 1e9))
        with mock.patch.object(A, "PAT", pats), mock.patch.object(PMV, "due", side_effect=due), \
             mock.patch.dict(A.SET, {"pensieve_low_gb": 50, "pensieve_after_review": "move", "pensieve_since": 1.0}), \
             mock.patch.object(A, "notify_c") as nc:
            with Usage(80): self.assertIsNone(A.pensieve_low_space(force=True))
            with Usage(30): info = A.pensieve_low_space(force=True)
            self.assertEqual(info["n"], 1); self.assertEqual(info["free_gb"], 30.0); self.assertTrue(nc.called)
            with mock.patch.dict(A.SET, {"pensieve_after_review": "off"}), Usage(30):
                self.assertEqual(A.pensieve_low_space(force=True)["n"], 2)                   # setting off: both offered
            with mock.patch.dict(A.SET, {"pensieve_low_gb": 0}), Usage(1):
                self.assertIsNone(A.pensieve_low_space(force=True))                          # 0 = never

    def test_free_space_run_moves_even_when_the_setting_is_off(self):
        A = self.app; import pensieve_move as PMV
        started = []
        class T:
            def __init__(self, target=None, args=(), **k): self.args = args
            def start(self): started.append(self.args)
            def is_alive(self): return False
        p = dict(code="LS3", status="done")
        with mock.patch.object(A, "PAT", [p]), mock.patch.object(PMV, "drive_ready", return_value=(True, "")), \
             mock.patch.object(PMV, "due", side_effect=lambda B_, p_, g=0, since=0.0, **k: not since), \
             mock.patch.dict(A.SET, {"pensieve_after_review": "off", "pensieve_since": 1.0}), \
             mock.patch.dict(A.PENSIEVE_RUN, {"thread": None}), mock.patch.object(A.threading, "Thread", T):
            A.pensieve_tick(); self.assertEqual(started, [])                                  # off: nothing moves by itself
            self.assertTrue(A.pensieve_api("free_space", {})["ok"])
            A.pensieve_tick(); self.assertEqual(started, [(p, True)])                         # the user's request: moved (Mac copy deleted)


if __name__ == "__main__":
    unittest.main()
