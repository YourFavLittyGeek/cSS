"""2026-11-26 training progress (user request): the training button reads "Training…" and is locked (disabled) while a cycle is
PREPARING or TRAINING (it used to look unchanged while preparing), and returns to "Start a training cycle" when the cycle ends;
the progress card shows the stages done / current / left, elapsed and remaining time; the screen refreshes itself in both states.
Also the image-learning envelope: 3 mm clinical SWI is learned from (user decision; header rounding tolerated), and the gathered
cache key carries the envelope so a changed limit re-extracts the patches.
Synthetic only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import shutil
import subprocess
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)
NODE = shutil.which("node"); JS = os.path.join(ROOT, "app", "percival_view.js")


class TestStages(unittest.TestCase):
    def setUp(self):
        import percival_gui as PG
        self.PG = PG; self.saved = dict(PG.JOB)

    def tearDown(self):
        self.PG.JOB.clear(); self.PG.JOB.update(self.saved)

    def test_stage_timing_and_states(self):
        PG = self.PG; now = time.time()
        PG.JOB.clear(); PG.JOB.update(state="preparing", stage="preparing", started=now - 30, heartbeat=now, progress=0.02, log=[], stage_times=dict(preparing=now - 30))
        j = PG.job_state()
        self.assertTrue(j["active"]); self.assertEqual(j["stages"][0]["status"], "current"); self.assertEqual(j["stages_left"], len(PG.STAGES) - 1)
        self.assertNotIn("stage_times", j)
        PG._transition("running", stage="components")
        PG.log("LUMOS image models fold 1/5", 0.16)                       # the engine's own message moves the stage
        j = PG.job_state(); S = {x["key"]: x["status"] for x in j["stages"]}
        self.assertEqual((S["preparing"], S["components"], S["discovery"]), ("done", "current", "left"))
        self.assertIn("LUMOS", j["stage_label"]); self.assertIsNotNone(j["elapsed_s"])
        PG._transition("failed", stage="failed", error="x")
        j = PG.job_state(); S = {x["key"]: x["status"] for x in j["stages"]}
        self.assertFalse(j["active"]); self.assertEqual(S["components"], "stopped")      # where it stopped, not "all left"

    def test_state_carries_the_job_card(self):
        src = open(os.path.join(ROOT, "app", "percival_gui.py")).read()
        i = src.index("def state():"); self.assertIn("job = job_state()", src[i:i + 600])


@unittest.skipIf(NODE is None, "node is not installed")
class TestButtonAndCard(unittest.TestCase):
    def run_js(self, expr):
        src = open(JS).read(); a = src.index("const PV_ACTIVE="); b = src.index("const PVMH=")
        code = "const esc=x=>String(x);" + src[a:b] + f"process.stdout.write(JSON.stringify({expr}))"
        r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
        if r.returncode: raise RuntimeError(r.stderr)
        return json.loads(r.stdout)

    def test_button_locked_in_both_active_states(self):
        for st in ("preparing", "running"):
            h = self.run_js(f'pvTrainBtn({{state:"{st}"}},"pv-train","Start a training cycle")')
            self.assertIn("Training…", h); self.assertIn("disabled", h); self.assertNotIn("Start a training cycle", h)
        for st in ("finished", "failed", "idle", "cancelled"):
            h = self.run_js(f'pvTrainBtn({{state:"{st}"}},"pv-train","Start a training cycle")')
            self.assertIn("Start a training cycle", h); self.assertNotIn("disabled", h)

    def test_card(self):
        j = dict(state="running", active=True, state_label="Training", progress=0.4, elapsed_s=605, heartbeat_age_s=3, stages_left=4,
                 eta=dict(eta_s=900, eta_range_s=[600, 1500], reliable=True),
                 stages=[dict(key="preparing", label="Preparing", status="done", duration_s=120), dict(key="components", label="Component models", status="current", duration_s=485)]
                        + [dict(key=f"s{i}", label=f"later {i}", status="left", duration_s=None) for i in range(4)],
                 log=["10:00:00 LUMOS image models fold 2/5"])
        h = self.run_js(f"pvJobCard({json.dumps(j)},true)")
        for t in ("stage 2 of 6", "Component models", "40 %", "Elapsed <b>10 min 5 s", "Remaining <b>15 min 0 s", "Stages left <b>4", "LUMOS image models fold 2/5"):
            self.assertIn(t, h)
        self.assertEqual(self.run_js('pvJobCard({state:"idle"},false)'), "")              # nothing to show in the header when idle

    def test_refresh_while_preparing(self):
        src = open(JS).read(); self.assertIn("if(PV_ACTIVE(job))PV.jt=setTimeout", src)
        self.assertNotIn('job.state==="running"?`training cycle…', src)


class TestEnvelope(unittest.TestCase):
    def test_three_mm_and_cache_key(self):
        from uengine.imaging import geometry as G
        self.assertEqual(G.MAX_SLICE_MM, 3.0)
        for z in (3.0, 3.000335, 2.999985): self.assertLessEqual(z, G.MAX_SLICE_MM + G.VOXEL_TOL_MM)
        self.assertGreater(3.5, G.MAX_SLICE_MM + G.VOXEL_TOL_MM)
        src = open(os.path.join(ROOT, "app", "percival_gui.py")).read(); self.assertIn('["envelope", _G.MAX_INPLANE_MM, _G.MAX_SLICE_MM', src)


if __name__ == "__main__":
    unittest.main()
