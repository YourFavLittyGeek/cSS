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


class TestDiskGuards(unittest.TestCase):
    def test_import_counts_only_the_chosen_series_and_refuses_when_full(self):
        import css_app as A
        ex = tempfile.mkdtemp(dir=os.environ["CSS_BASE"])
        for name, n in (("SWI", 3), ("T1", 2), ("LOCALIZER", 50), ("DWI", 40)):          # 15-series exams: only the chosen ones are copied
            os.makedirs(os.path.join(ex, name))
            for i in range(n): open(os.path.join(ex, name, f"{i}.dcm"), "wb").write(b"x" * 1000)
        plan = dict(exams=[dict(include=True, chosen=dict(SWI=os.path.join(ex, "SWI"), T1=os.path.join(ex, "T1"))),
                           dict(include=False, chosen=dict(SWI=os.path.join(ex, "DWI")))])
        r = A.import_space_check(plan); self.assertTrue(r["ok"], r); self.assertAlmostEqual(r["need_gb"], 5000 / 1024**3, places=2)
        with mock.patch.object(A, "_free_gb", return_value=10.0):
            r = A.import_space_check(plan)
        self.assertFalse(r["ok"]); self.assertIn("nothing was copied", r["error"])

    def test_no_new_study_starts_when_the_disk_is_nearly_full(self):
        import css_app as A
        with mock.patch.object(A, "_free_gb", return_value=5.0), mock.patch.object(A, "notify_c") as n:
            self.assertIn("processing paused", A._disk_gate()); A._disk_gate()
        self.assertEqual(n.call_count, 1)                                              # one notification, not one per second
        with mock.patch.object(A, "_free_gb", return_value=500.0): self.assertEqual(A._disk_gate(), "")
        self.assertEqual(A.CUR["disk_wait"], "")


class TestTemporaryCopyCleanup(unittest.TestCase):
    def _study(self, code, status="done"):
        import source_cleanup as SRC
        B = tempfile.mkdtemp(dir=os.environ["CSS_BASE"]); AD = os.path.join(B, "app_data")
        for d in (f"{AD}/import_src/{code}/SWI", f"{B}/raw/{code}/SWI/_dicom", f"{B}/review", f"{AD}/staging/{code}/SWI"):
            os.makedirs(d, exist_ok=True)
        open(f"{AD}/import_src/{code}/SWI/SWI_00000.dcm", "wb").write(b"d" * 4000)
        open(f"{B}/raw/{code}/SWI/_dicom/00000_a.dcm", "wb").write(b"d" * 4000)
        open(f"{B}/raw/{code}/SWI/{code}_swi.nii.gz", "wb").write(b"n" * 100)
        t0 = time.time() - 60
        p = dict(code=code, status=status, started=t0, finished=time.time())
        for f in (f"{B}/review/{code}_candidates.csv", f"{B}/review/{code}_manifest.json"): open(f, "w").write("x")
        return SRC, B, AD, p

    def test_only_completely_processed_studies_lose_their_dicom_copies(self):
        SRC, B, AD, p = self._study("S1")
        self.assertEqual(SRC.verified(B, p), "")
        self.assertGreaterEqual(SRC.clean(B, AD, p), 8000)
        self.assertFalse(os.path.exists(f"{AD}/import_src/S1")); self.assertFalse(os.path.exists(f"{B}/raw/S1/SWI/_dicom"))
        self.assertTrue(os.path.exists(f"{B}/raw/S1/SWI/S1_swi.nii.gz"))                      # the conversion re-runs use is kept
        self.assertTrue(os.path.exists(f"{B}/review/S1_candidates.csv"))                       # results kept
        for status in ("failed", "stopped", "running", "waiting"):
            SRC2, B2, AD2, p2 = self._study("S2", status)
            self.assertIn("status", SRC2.verified(B2, p2)); self.assertEqual(SRC2.clean(B2, AD2, p2), 0); self.assertTrue(os.path.exists(f"{AD2}/import_src/S2"))

    def test_done_label_without_real_results_is_not_trusted(self):
        SRC, B, AD, p = self._study("S3"); os.remove(f"{B}/review/S3_manifest.json")
        self.assertIn("manifest", SRC.verified(B, p))
        SRC, B, AD, p = self._study("S4"); p["started"] = time.time() + 100; p["finished"] = time.time() + 200
        self.assertIn("older than the last run", SRC.verified(B, p))
        SRC, B, AD, p = self._study("S5"); os.remove(f"{B}/raw/S5/SWI/S5_swi.nii.gz")
        self.assertIn("no converted SWI", SRC.verified(B, p)); self.assertEqual(SRC.clean(B, AD, p), 0)

    def test_policies_keep_days_and_never(self):
        SRC, B, AD, p = self._study("S6")
        self.assertEqual(SRC.sweep(B, AD, [p], "keep", 7), (0, 0))
        self.assertEqual(SRC.sweep(B, AD, [p], "keep_days", 7)[0], 0)                          # finished just now: kept for 7 days
        self.assertEqual(SRC.sweep(B, AD, [p], "after_processing", 7, running={"S6"})[0], 0)   # never while running
        p["finished"] = time.time() - 8 * 86400; p["started"] = p["finished"] - 60
        for f in (f"{B}/review/S6_candidates.csv", f"{B}/review/S6_manifest.json"): os.utime(f, (p["started"] + 10, p["started"] + 10))
        self.assertEqual(SRC.sweep(B, AD, [p], "keep_days", 7)[0], 1); self.assertFalse(os.path.exists(f"{AD}/import_src/S6"))
        sm = SRC.summary(B, AD, [p], "keep_days", 7); self.assertEqual(sm["studies"], [])

    def test_rerun_after_cleanup_uses_the_conversion(self):
        import css_app as A
        code = "RR1"; raw = os.path.join(A.B, "raw", code, "SWI"); os.makedirs(raw, exist_ok=True); open(os.path.join(raw, "x.nii.gz"), "wb").write(b"n")
        d = A.stage(dict(code=code, series=dict(SWI=os.path.join(A.AD, "import_src", code, "SWI"))))
        self.assertTrue(os.path.isdir(os.path.join(d, "SWI")))                                  # cohort.py finds the modality and reuses raw/
        with self.assertRaises(FileNotFoundError):
            A.stage(dict(code="RR2", series=dict(SWI=os.path.join(A.AD, "import_src", "RR2", "SWI"))))   # never converted: clear error


class TestFreshProjectRunsTheWizard(unittest.TestCase):
    def _mgr(self, vault):
        from uengine.setup.setup_state_manager import SetupStateManager
        ws = tempfile.mkdtemp(dir=os.environ["CSS_BASE"]); os.makedirs(os.path.join(ws, "app_data"))
        import sqlite3
        con = sqlite3.connect(os.path.join(ws, "app_data", "pensieve.db"))
        con.execute("CREATE TABLE studies_memory (id TEXT, pad BLOB)"); con.execute("CREATE TABLE expert_annotations (id TEXT)")
        con.execute("PRAGMA user_version=1"); [con.execute(f"CREATE TABLE t{i} (x TEXT)") for i in range(30)]; con.commit(); con.close()   # empty schema, > 4 KB
        return ws, (lambda: SetupStateManager(ws, vault_root=vault))

    def test_empty_vault_and_empty_pensieve_are_not_an_installation(self):
        vault = tempfile.mkdtemp(dir=os.environ["CSS_BASE"])
        for d in ("studies", "PENSIEVE/Manifests", "manifest"): os.makedirs(os.path.join(vault, d))
        ws, M = self._mgr(vault)
        self.assertFalse(M().get_state()["completed"])                                       # wizard runs
        os.makedirs(os.path.join(vault, "studies", "S001"))
        ws2, M2 = self._mgr(vault)
        self.assertTrue(M2().get_state()["completed"])                                       # a vault with studies still counts

    def test_wrong_auto_completion_is_reverted(self):
        import json
        vault = tempfile.mkdtemp(dir=os.environ["CSS_BASE"]); os.makedirs(os.path.join(vault, "studies"))
        ws, M = self._mgr(vault)
        json.dump(dict(state="SETUP_COMPLETED", completed=True, is_first_launch=False, current_step=7, validated_config={},
                       history=[dict(event="legacy_installation_detected_and_migrated")]), open(os.path.join(ws, "app_data", "setup_state.json"), "w"))
        st = M().get_state()
        self.assertFalse(st["completed"]); self.assertEqual(st["history"][-1]["event"], "auto_completion_reverted_empty_project")
        json.dump(dict(state="SETUP_COMPLETED", completed=True, validated_config=dict(workspace_valid=True),
                       history=[dict(event="setup_completed")]), open(os.path.join(ws, "app_data", "setup_state.json"), "w"))
        self.assertTrue(M().get_state()["completed"])                                        # a real completed setup is never reverted


if __name__ == "__main__":
    unittest.main()
