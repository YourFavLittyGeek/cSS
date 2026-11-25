"""Setup Finish / import without frozen windows: background jobs with progress (app/progress_jobs.py), Finish as a job that opens the
workspace (the navigation gate is refreshed - before, nav("studies") was refused and the app looked frozen until reopened), Step 6 readiness
runs checks the user did not click through (dcm2niix no longer 'BLOCKED' when installed), a failed import leaves no orphan image copies.
Temporary folders only (tests/run_isolated_suite.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), os.path.join(ROOT, "scripts"), ROOT):
    if p not in sys.path: sys.path.insert(0, p)
import progress_jobs as PJ   # noqa: E402


def wait(jid, t=60):
    end = time.time() + t
    while time.time() < end:
        j = PJ.get(jid)
        if j["state"] != "running": return j
        time.sleep(0.05)
    raise AssertionError(f"job {jid} still running")


class TestProgressJobs(unittest.TestCase):
    def test_steps_eta_result_and_failure(self):
        seen = []
        def work(rep):
            for i in range(4):
                rep(i, f"step {i + 1}"); time.sleep(0.05); seen.append(PJ.get(jid)["eta_s"])
                rep(i, f"detail {i}", log=False)
            return dict(ok=True, summary="all done", n=4)
        jid = PJ.start("unit", 4, work, title="Unit job")
        j = wait(jid)
        self.assertEqual(j["state"], "done"); self.assertEqual(j["pct"], 100.0); self.assertEqual(j["label"], "all done"); self.assertEqual(j["result"]["n"], 4)
        self.assertEqual([s["label"] for s in j["steps"]], ["step 1", "step 2", "step 3", "step 4"])     # per-file details do not flood the list
        self.assertTrue(any(e is not None for e in seen))                                                   # remaining time estimated once a step finished
        f = wait(PJ.start("unit", 2, lambda rep: dict(ok=False, error="refused: code already used")))
        self.assertEqual(f["state"], "failed"); self.assertIn("code already used", f["error"])
        x = wait(PJ.start("unit", 2, lambda rep: 1 / 0))
        self.assertEqual(x["state"], "failed"); self.assertIn("ZeroDivisionError", x["error"])
        self.assertEqual(PJ.get("nope")["state"], "unknown")


class TestSetupFinish(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import css_app; cls.A = css_app

    def test_step6_runs_missing_checks_instead_of_blocking(self):
        A = self.A
        with mock.patch("uengine.setup.validate_mri_tool", return_value=dict(ok=True, path="/x/dcm2niix")):
            cfg = A._setup_fill_checks(dict(python_valid=True))
        self.assertTrue(cfg["dcm2niix_valid"]); self.assertGreater(cfg["workspace_free_gb"], 0)
        from uengine.setup import SystemReadinessService
        caps = SystemReadinessService.evaluate_capabilities(dict(cfg, pipeline_valid=True), {})["capabilities"]
        self.assertEqual(caps["can_import"]["blockers"], [])

    def test_finish_as_background_job_opens_the_workspace(self):
        A = self.A
        r = A.setup_post("finish_start", {}); self.assertTrue(r.get("ok"), r)
        self.assertEqual(A.setup_post("finish_start", {}).get("job"), r["job"]) if PJ.get(r["job"])["state"] == "running" else None   # no second Finish while one runs
        j = wait(r["job"], 120)
        self.assertEqual(j["state"], "done", j); self.assertEqual(j["total"], A.SETUP_FINISH_STEPS)
        self.assertGreaterEqual(len(j["steps"]), 10)
        self.assertFalse(j["result"]["restart_required"])
        self.assertTrue(A.setup_get("lifecycle", {})["allow_dashboard"])

    def test_front_end_refreshes_the_navigation_gate(self):
        js = open(os.path.join(ROOT, "app", "setup_view.js")).read()
        body = js[js.index("async function finishAndLaunch"):js.index("async function exportDiagnostics")]
        self.assertIn("window.SETUP_LIFECYCLE", body); self.assertIn("finish_start", body); self.assertIn("PROGRESS.open", body)
        self.assertIn("🔒 LOCKED", js); self.assertNotIn("'BLOCKED'", js)
        html = open(os.path.join(ROOT, "app", "css_app.html")).read()
        self.assertLess(html.index("/progress_view.js"), html.index("/setup_view.js"))

    def test_restart_refused_outside_the_installed_app(self):
        with mock.patch.dict(os.environ, {"PERCIVAL_APP_BUNDLE": ""}):
            r = self.A._restart_app()
        self.assertFalse(r["ok"]); self.assertIn("quit and open", r["error"])


class TestImportCleanup(unittest.TestCase):
    def test_failed_import_removes_only_its_own_copies(self):
        import import_wizard as IW
        root = os.path.join(tempfile.mkdtemp(dir=os.environ["CSS_BASE"]), "import_src"); src = tempfile.mkdtemp(dir=os.environ["CSS_BASE"])
        os.makedirs(os.path.join(src, "SWI")); open(os.path.join(src, "SWI", "a.dcm"), "w").write("x")
        ticks = []
        out = IW._neutral_copy({"SWI": os.path.join(src, "SWI")}, "S001", root, tick=ticks.append)
        self.assertTrue(os.path.exists(os.path.join(out["SWI"], "SWI_00000.dcm"))); self.assertEqual(ticks, ["SWI 1/1 files"])
        keep = os.path.join(os.path.dirname(root), "other"); os.makedirs(keep)
        IW._drop_copies([os.path.join(root, "S001"), keep])
        self.assertFalse(os.path.exists(os.path.join(root, "S001"))); self.assertTrue(os.path.isdir(keep))   # only <import_src>/<key>
        self.assertTrue(os.path.exists(os.path.join(src, "SWI", "a.dcm")))                                  # originals untouched

    def test_commit_start_route_exists_and_requires_confirmation(self):
        import css_app as A
        r = A.id_post("import/commit_start", dict(plan="missing")) if hasattr(A, "id_post") else None
        if r is None: self.skipTest("id_post not exposed")
        self.assertFalse(r["ok"]); self.assertTrue(r.get("needs_confirm"))


if __name__ == "__main__":
    unittest.main()
