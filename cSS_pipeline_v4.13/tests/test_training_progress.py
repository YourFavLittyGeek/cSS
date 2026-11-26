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

    def test_in_place_updates_no_page_rebuild(self):
        """the screen used to be rebuilt every 2.5 s (and twice as often on Model Center): now only the card + button change"""
        src = open(JS).read(); a = src.index("const PV_ACTIVE="); b = src.index("const PVMH=")
        sim = r"""
const esc=x=>String(x);const PV={tab:"system",jg:1};let V="intel";let rebuilt=0;const intelView=()=>{rebuilt++};const toast=()=>{};
const slot0={dataset:{pvJobslot:"0"},innerHTML:"old"},slot1={dataset:{pvJobslot:"1"},innerHTML:"old"};
const btn={disabled:false,textContent:"Start a training cycle"};
const v={querySelectorAll:q=>q==="[data-pv-jobslot]"?[slot0,slot1]:[]};
globalThis.document={getElementById:id=>id==="pv-train"?btn:null};globalThis.window={scrollY:420,scrollTo:(x,y)=>{globalThis.sy=y}};
let J={state:"running",active:true,progress:.3,stages:[],log:[]};const api=async()=>J;
let timers=0;globalThis.setTimeout=()=>{timers++;return timers};globalThis.clearTimeout=()=>{};
""" + src[a:b] + r"""
(async()=>{await pvJobPoll(v,1);const r1=[rebuilt,slot0.innerHTML.includes("30 %"),slot1.innerHTML.includes("30 %"),btn.disabled,btn.textContent,timers,globalThis.sy];
 await pvJobPoll(v,0);const r2=[rebuilt,timers];                      // a stale chain stops by itself
 J={state:"finished",progress:1};await pvJobPoll(v,1);const r3=[rebuilt,timers];
 process.stdout.write(JSON.stringify([r1,r2,r3]))})()"""
        r = subprocess.run([NODE, "-e", sim], capture_output=True, text=True, timeout=30)
        if r.returncode: raise RuntimeError(r.stderr)
        r1, r2, r3 = json.loads(r.stdout)
        self.assertEqual(r1, [0, True, True, True, "Training…", 1, 420])      # no rebuild, card + button updated, scroll kept, one timer
        self.assertEqual(r2, [0, 1])                                          # stale chain: nothing, no new timer
        self.assertEqual(r3, [1, 1])                                          # cycle over: ONE full refresh, no further timer
        self.assertIn("clearTimeout(PV.sht)", src)                            # Model Center shadow poll: one chain

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
