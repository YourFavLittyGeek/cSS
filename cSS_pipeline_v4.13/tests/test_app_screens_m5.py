"""2026-11-28 Milestone 5 (audit 2026-11-27 G2-G6, C3): screens without a real backend.
- File Manager: every action button has a handler that calls the guarded backend; delete moves to the Trash (protected files refused);
- Settings: no fake 'Operational' / zero values; placeholder sections replaced by server state ('unavailable' when it cannot be read);
  the dead pre-flight toggle is gone;
- retired uScore prototype notifications only when the prototypes are switched on; obsolete 'Unified' wording gone.
Temporary folders only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))
FMJS = open(os.path.join(ROOT, "app", "file_manager_view.js")).read()
SETJS = open(os.path.join(ROOT, "app", "settings_view.js")).read()


class TestFileManager(unittest.TestCase):
    def test_every_button_has_a_handler(self):
        for bid in ("fm-mkdir", "fm-copy", "fm-move", "fm-archive", "fm-restore", "fm-del"):
            self.assertIn(f'id="{bid}"', FMJS); self.assertRegex(FMJS, rf'\$\("#{bid}"\);\s*if \(\w+\) \w+\.onclick')
        for attr in ("data-rename", "data-verify", "data-del"):
            self.assertIn(f'querySelectorAll("[{attr}]")', FMJS)
        for ep in ("mkdir", "copy", "move", "archive", "restore", "delete", "rename", "verify"):
            self.assertIn(f'"/api/files/{ep}"', FMJS)
        self.assertIn('t !== "TRASH"', FMJS)                                      # typed confirmation before anything leaves

    def test_delete_goes_to_the_trash_and_protected_is_refused(self):
        from uengine.file_manager import FileManager
        b = tempfile.mkdtemp(prefix="fm_"); os.makedirs(os.path.join(b, "work")); os.makedirs(os.path.join(b, "review"))
        p = os.path.join(b, "work", "scratch.txt"); open(p, "w").write("x")
        r = FileManager(b).delete_item(p, confirm=True)
        self.assertTrue(r["ok"], r); self.assertFalse(os.path.exists(p)); self.assertTrue(os.path.exists(r["moved_to_trash"]))
        self.assertTrue(r["moved_to_trash"].startswith(os.path.join(os.path.expanduser("~"), ".Trash")))
        q = os.path.join(b, "review", "S1_calls.csv"); open(q, "w").write("x")
        self.assertFalse(FileManager(b).delete_item(q, confirm=True)["ok"]); self.assertTrue(os.path.exists(q))   # reviews are protected
        self.assertFalse(FileManager(b).delete_item(p, confirm=False)["ok"])


class TestSettings(unittest.TestCase):
    def test_no_fake_values(self):
        i = SETJS.index("async function renderSectionPensieve(el)"); body = SETJS[i:SETJS.index("async function renderSectionTraining", i)]
        self.assertNotIn('|| "Operational"', body); self.assertNotIn("total_candidates || 0", body); self.assertIn("/api/percival/pensieve_index", body)
        for fn, ep in (("renderSectionTraining", "/api/percival/readiness"), ("renderSectionModels", "/api/percival/state"),
                       ("renderSectionActivity", "/api/percival/events"), ("renderSectionArchive", "/api/state")):
            i = SETJS.index(f"async function {fn}(el)"); self.assertIn(ep, SETJS[i:i + 1500])
        self.assertIn("unavailable", SETJS); self.assertNotIn('data-pf="preflight"', SETJS)
        self.assertNotIn("14-section", SETJS); self.assertNotIn("pensieve_core.db", SETJS)


class TestLabels(unittest.TestCase):
    def test_retired_prototype_notices(self):
        app = open(os.path.join(ROOT, "app", "css_app.py")).read(); h = open(os.path.join(ROOT, "app", "css_app.html")).read()
        self.assertIn('proto = bool(SET["features"].get("show_prototypes"))', app)
        self.assertNotRegex(app, r'f"Unified \{n\}'); self.assertNotIn('"Open Unified"', h)


if __name__ == "__main__":
    unittest.main()
