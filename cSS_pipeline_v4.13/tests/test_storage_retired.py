"""2026-11-25 audit items 5-8: the overlapping archive / stage / sync / transfer-queue actions answer "retired" (one owner:
the Pensieve move); "Free up Mac space" and staging prune never touch a study being processed and report link sizes."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)


class TestRetired(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import css_app
        cls.app = css_app

    def test_overlapping_actions_are_retired(self):
        for fn, op, d in (("storage_post", "archive", dict(code="R1")), ("storage_post", "stage", dict(code="R1")),
                          ("storage_post", "clean", dict(code="R1")), ("storage_post", "verify", dict(code="R1")),
                          ("storage_post", "sync_execute", dict(preview={})), ("workspace_post", "stage", dict(study_id="R1")),
                          ("workspace_post", "archive", dict(study_id="R1")), ("workspace_post", "clean", dict(study_id="R1")),
                          ("transfer_post", "process_next", {}), ("transfer_post", "enqueue", dict(study_code="R1"))):
            with self.subTest(op=f"{fn} {op}"):
                r = getattr(self.app, fn)(op, d)
                self.assertFalse(r["ok"])
                self.assertTrue(r.get("retired"), r)
                self.assertIn("Pensieve", r["error"])

    def test_free_space_skips_running_studies_and_counts_links(self):
        from uengine.transfer_manager import TransferManager
        B = self.app.B
        big = os.path.join(B, "app_data", "import_src", "RUN1", "SWI", "a.dcm"); os.makedirs(os.path.dirname(big), exist_ok=True)
        open(big, "wb").write(b"x" * 100000)
        for code in ("RUN1", "IDLE1"):
            d = os.path.join(B, "app_data", "staging", code, "SWI"); os.makedirs(d, exist_ok=True)
            ln = os.path.join(d, "a.dcm")
            if not os.path.lexists(ln): os.symlink(big, ln)
        tm = TransferManager(B)
        prev = {it["study_code"]: it for it in tm.free_up_mac_space_preview()["items"] if it["category"] == "staging"}
        self.assertLess(prev["IDLE1"]["size_bytes"], 1000)                     # the link, not the 100 kB DICOM it points to
        tm.execute_free_up_mac_space(skip_codes={"RUN1"})
        self.assertTrue(os.path.lexists(os.path.join(B, "app_data", "staging", "RUN1", "SWI", "a.dcm")))   # running: untouched
        self.assertFalse(os.path.lexists(os.path.join(B, "app_data", "staging", "IDLE1", "SWI", "a.dcm")))
        self.assertTrue(os.path.exists(big))                                   # the import copy itself is never touched


if __name__ == "__main__":
    unittest.main()
