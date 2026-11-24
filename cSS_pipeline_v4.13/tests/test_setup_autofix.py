"""Setup without Terminal: FreeSurfer found automatically (versioned folders, Finder-started app without FREESURFER_HOME), the Data Vault
(<drive>/PERCIVAL_VAULT) created automatically when the chosen drive is connected - never on an unplugged drive, an existing vault never
changed - and the setup wizard's own key names (freesurfer_home / fs_license) saved. Temporary folders only (tests/run_isolated_suite.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), os.path.join(ROOT, "scripts"), ROOT):
    if p not in sys.path: sys.path.insert(0, p)
import setup_gui as SG   # noqa: E402


def tmp(): return tempfile.mkdtemp(prefix="autofix_", dir=os.environ["CSS_BASE"])


def fake_fs(home, version="8.2.0"):
    os.makedirs(os.path.join(home, "bin"), exist_ok=True)
    for t in SG.FS_REQUIRED_TOOLS: open(os.path.join(home, "bin", t), "w").close()
    with open(os.path.join(home, "build-stamp.txt"), "w") as f: f.write(f"freesurfer-macOS-darwin_arm64-{version}-20250101")
    return home


class TestFindFreeSurfer(unittest.TestCase):
    def test_versioned_subfolder_found_newest_first_and_validated(self):
        r = os.path.join(tmp(), "freesurfer"); fake_fs(os.path.join(r, "7.4.1"), "7.4.1"); fake_fs(os.path.join(r, "8.2.0"))
        os.makedirs(os.path.join(r, "9.0.0-incomplete"))                       # not an installation (no bin/ tools) -> skipped
        with mock.patch.dict(os.environ, PERCIVAL_FS_SEARCH=r):
            self.assertEqual(SG.find_freesurfer(), os.path.join(r, "8.2.0"))
            self.assertEqual(SG.find_freesurfer(os.path.join(r, "7.4.1")), os.path.join(r, "7.4.1"))   # FREESURFER_HOME wins when valid
        with mock.patch.dict(os.environ, PERCIVAL_FS_SEARCH=tmp()):
            self.assertEqual(SG.find_freesurfer(), "")                       # nothing usable -> "" (reported, never assumed)


class TestVault(unittest.TestCase):
    def test_drive_or_folder_means_percival_vault_inside(self):
        self.assertEqual(SG.resolve_vault_path("/Volumes/Percival"), "/Volumes/Percival/PERCIVAL_VAULT")
        self.assertEqual(SG.resolve_vault_path("/Volumes/Percival/PERCIVAL_VAULT/"), "/Volumes/Percival/PERCIVAL_VAULT")

    def test_created_automatically_then_never_changed(self):
        drive = tmp()
        r = SG.ensure_vault(drive); vp = os.path.join(drive, "PERCIVAL_VAULT")
        self.assertTrue(r["ok"] and r["created"], r); self.assertEqual(r["path"], vp)
        man = os.path.join(vp, "manifest", "vault_manifest.json"); self.assertTrue(os.path.exists(man))
        before = open(man).read()
        r2 = SG.ensure_vault(vp); self.assertTrue(r2["ok"]); self.assertFalse(r2["created"]); self.assertEqual(open(man).read(), before)

    def test_unplugged_drive_never_creates_anything(self):
        p = "/Volumes/PercivalTestDriveNotConnected_9f3"
        r = SG.ensure_vault(p)
        self.assertFalse(r["ok"]); self.assertIn("not connected", r["error"]); self.assertFalse(os.path.exists(p))
        self.assertFalse(SG.ensure_vault("")["ok"])

    def test_leftover_folder_of_an_unplugged_drive_is_not_a_drive(self):
        left = tempfile.mkdtemp(prefix="UnpluggedDrive_", dir=os.environ["PERCIVAL_VOLUMES_ROOT"])   # unique: other tests create vaults under <volumes root>/Percival   # a folder, not a mount point
        r = SG.ensure_vault(left)
        self.assertFalse(r["ok"]); self.assertIn("not connected", r["error"]); self.assertFalse(os.path.exists(os.path.join(left, "PERCIVAL_VAULT")))

    def test_read_only_parent_refused(self):
        d = tmp(); os.chmod(d, 0o500)
        try: r = SG.ensure_vault(d); self.assertFalse(r["ok"]); self.assertFalse(os.path.exists(os.path.join(d, "PERCIVAL_VAULT")))
        finally: os.chmod(d, 0o700)


class TestAppWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import css_app; cls.app = css_app

    def test_wizard_keys_saved_and_vault_created_on_save(self):
        A = self.app; fs = fake_fs(os.path.join(tmp(), "fs", "8.2.0")); drive = tmp()
        lic = os.path.join(tmp(), "license.txt")
        with open(lic, "w") as f: f.write("someone@example.org\n12345\n *Cabcdefgh\n FSabcdefgh\n")
        r = A.setup_post("save_config", dict(freesurfer_home=fs, fs_license=lic, vault_mount=drive))
        self.assertTrue(r["ok"], r)
        self.assertEqual(A.SET["freesurfer_home"], fs); self.assertEqual(A.SET["fs_license"], lic)
        self.assertEqual(A.SET["vault_mount"], os.path.join(drive, "PERCIVAL_VAULT")); self.assertTrue(r["saved"]["vault_created"])
        vc = json.load(open(os.path.expanduser("~/.percival_vault_config.json")))
        self.assertEqual(vc["active_vault_path"], os.path.join(drive, "PERCIVAL_VAULT"))      # the key uengine.vault reads

    def test_autofix_finds_freesurfer_and_creates_vault_when_drive_appears(self):
        A = self.app; r = os.path.join(tmp(), "freesurfer"); fs = fake_fs(os.path.join(r, "8.2.0")); drive = tmp()
        old = {k: A.SET.get(k) for k in ("freesurfer_home", "vault_mount")}
        try:
            A.SET["freesurfer_home"] = ""; A.SET["vault_mount"] = drive
            with mock.patch.dict(os.environ, PERCIVAL_FS_SEARCH=r):
                with mock.patch.dict(os.environ, {"FREESURFER_HOME": ""}): self.assertTrue(A.storage_autofix())
            self.assertEqual(A.SET["freesurfer_home"], fs)
            self.assertEqual(A.SET["vault_mount"], os.path.join(drive, "PERCIVAL_VAULT"))
            self.assertTrue(os.path.exists(os.path.join(drive, "PERCIVAL_VAULT", "manifest", "vault_manifest.json")))
            with mock.patch.dict(os.environ, PERCIVAL_FS_SEARCH=r): self.assertFalse(A.storage_autofix())    # nothing left to fix
        finally:
            for k, v in old.items():
                if v is None: A.SET.pop(k, None)
                else: A.SET[k] = v

    def test_setup_check_reports_the_real_vault_state(self):
        A = self.app; drive = tmp()
        items = {i["id"]: i for i in SG.checks(A.B, A.AD, dict(vault_mount=drive), A.fs_env, A.find_license, A.which, os.path.join(ROOT, "unified_engine"))}
        self.assertFalse(items["vault"]["ok"]); self.assertIn("created automatically", items["vault"]["detail"])
        SG.ensure_vault(drive)
        items = {i["id"]: i for i in SG.checks(A.B, A.AD, dict(vault_mount=drive), A.fs_env, A.find_license, A.which, os.path.join(ROOT, "unified_engine"))}
        self.assertTrue(items["vault"]["ok"]); self.assertIn("vault ready", items["vault"]["detail"])


if __name__ == "__main__":
    unittest.main()
