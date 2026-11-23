"""Phase 0 regression tests: the unittest suite is isolated from the live research project (I1-I4 of the test matrix).

Every write probe targets a path whose PARENT DOES NOT EXIST inside the real home / under /Volumes. With the guard working
the probe raises IsolationViolation; if the guard were broken the OS would raise FileNotFoundError instead - so a broken
guard makes the test FAIL without ever creating anything. The deliberate refusals are removed from the violation log."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import sqlite3
import subprocess
import sys
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

ST = _isolation.STATE
REAL_HOME = _isolation.REAL_HOME


class TestPhase0Isolation(unittest.TestCase):
    def setUp(self):
        self.tag = f"__phase0_probe_{uuid.uuid4().hex}"
        self.n_viol = len(ST["violations"])

    def tearDown(self):
        # the refusals provoked on purpose by this test are expected; anything else stays in the log
        ST["violations"][:] = ST["violations"][:self.n_viol] + [v for v in ST["violations"][self.n_viol:] if self.tag not in v]

    # I1 ------------------------------------------------------------------------------------------------------------
    def test_i1_home_and_base_are_temporary(self):
        home = os.path.realpath(os.path.expanduser("~"))
        self.assertNotEqual(home, REAL_HOME)
        self.assertFalse(_isolation._inside(home, REAL_HOME))
        self.assertTrue(_isolation._inside(home, ST["root"]))
        self.assertTrue(_isolation._inside(os.path.realpath(os.environ["CSS_BASE"]), ST["root"]))
        self.assertTrue(_isolation._inside(os.path.realpath(os.environ["PERCIVAL_VOLUMES_ROOT"]), ST["root"]))
        from uengine.safety import volumes_root, real_home
        self.assertEqual(os.path.realpath(volumes_root()), os.path.realpath(os.environ["PERCIVAL_VOLUMES_ROOT"]))
        self.assertEqual(os.path.realpath(real_home()), REAL_HOME)          # pwd-based, not fooled by $HOME
        self.assertTrue(sys.dont_write_bytecode)

    # I2 ------------------------------------------------------------------------------------------------------------
    def test_i2_css_app_binds_to_the_temporary_project_without_side_effects(self):
        import css_app
        self.assertTrue(_isolation._inside(os.path.realpath(css_app.B), ST["root"]))
        self.assertFalse(css_app._APP_STARTUP)
        self.assertEqual(css_app.PM_RECOVERED, {})                          # crash recovery did not run on import
        self.assertFalse(os.path.exists(os.path.join(css_app.B, "scripts", "run_css.sh")))   # no pipeline install on import
        with self.assertRaises(RuntimeError):
            css_app._refuse_live_binding_under_test(os.path.join(REAL_HOME, "Percival_project"))
        with self.assertRaises(RuntimeError):
            css_app._refuse_live_binding_under_test("/Volumes/Percival/PERCIVAL_VAULT")

    # I3 ------------------------------------------------------------------------------------------------------------
    def test_i3_writes_into_the_real_home_are_refused(self):
        missing = os.path.join(REAL_HOME, "Percival_project", self.tag)
        with self.assertRaises(_isolation.IsolationViolation):
            open(os.path.join(missing, "probe.txt"), "w")
        with self.assertRaises(_isolation.IsolationViolation):
            os.mkdir(os.path.join(REAL_HOME, self.tag, "sub"))
        with self.assertRaises(_isolation.IsolationViolation):
            os.remove(os.path.join(REAL_HOME, self.tag))
        with self.assertRaises(_isolation.IsolationViolation):
            os.replace(os.path.join(ST["root"], "nothing"), os.path.join(missing, "x"))
        with self.assertRaises(_isolation.IsolationViolation):
            sqlite3.connect(os.path.join(missing, "probe.db"))
        with self.assertRaises(_isolation.IsolationViolation):          # 1e: write-mode sqlite URIs are still refused
            sqlite3.connect(f"file:{os.path.join(missing, 'probe.db')}?mode=rwc", uri=True)
        self.assertFalse(os.path.exists(missing))

    def test_i3_writes_under_volumes_are_refused(self):
        with self.assertRaises(_isolation.IsolationViolation):
            open(os.path.join("/Volumes", self.tag, "probe.txt"), "w")
        with self.assertRaises(_isolation.IsolationViolation):
            os.mkdir(os.path.join("/Volumes", self.tag, "sub"))

    def test_i3_writes_in_the_temporary_tree_are_allowed(self):
        p = os.path.join(ST["root"], "tmp", f"{self.tag}.txt")
        with open(p, "w") as f:
            f.write("ok")
        os.remove(p)

    # I4 ------------------------------------------------------------------------------------------------------------
    def test_i4_diskutil_and_programs_on_live_data_are_refused(self):
        # (a broken guard would only make diskutil report "no such volume" for these non-existent paths)
        for verb in ("unmount", "eject", "unmountDisk"):
            with self.assertRaises(_isolation.IsolationViolation):
                subprocess.run(["diskutil", verb, f"/nonexistent/{self.tag}"], capture_output=True)
        with self.assertRaises(_isolation.IsolationViolation):
            subprocess.run(["/usr/sbin/diskutil", "unmount", "force", f"/nonexistent/{self.tag}"], capture_output=True)
        with self.assertRaises(_isolation.IsolationViolation):
            subprocess.run(["ls", os.path.join(REAL_HOME, "Percival_project", self.tag)], capture_output=True)

    def test_i4_eject_manager_never_runs_diskutil_under_isolation(self):
        from uengine.storage.eject_manager import EjectManager
        em = EjectManager.__new__(EjectManager)
        em._runner = None
        with self.assertRaises(RuntimeError):
            em._run(["diskutil", "unmount", f"/nonexistent/{self.tag}"])


if __name__ == "__main__":
    unittest.main()
