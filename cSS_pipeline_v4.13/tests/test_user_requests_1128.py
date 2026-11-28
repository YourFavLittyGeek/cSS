"""2026-11-28 user requests: (1) the training card says 'Training complete' with the finish time when a cycle ends (it showed 'Stages left 0
of 7', read as 0/7) and the last cycle after an app restart; (2) one Emergency eject button on every screen that stops ALL transfers at a
safe point, holds new drive work and unmounts the drive. (CORE removal: test_stage1_retirement.TestCoreRemoved.)
No drive is touched: the transfer pool and the eject manager are replaced by fakes. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)
NODE = shutil.which("node"); JS = os.path.join(ROOT, "app", "percival_view.js")


@unittest.skipIf(NODE is None, "node is not installed")
class TestCard(unittest.TestCase):
    def js(self, expr):
        src = open(JS).read(); a = src.index("const PV_ACTIVE="); b = src.index("const PVMH=")
        r = subprocess.run([NODE, "-e", "const esc=x=>String(x);" + src[a:b] + f"process.stdout.write(JSON.stringify({expr}))"], capture_output=True, text=True, timeout=30)
        if r.returncode: raise RuntimeError(r.stderr)
        return json.loads(r.stdout)

    def test_finished_card(self):
        st = [dict(key=f"s{i}", label=f"stage {i}", status="done", duration_s=60) for i in range(7)]
        j = dict(state="finished", progress=1, elapsed_s=1241, finished_at="2026-11-28 07:56", stages=st, last_run=dict(version="v002", finished="2026-11-28 07:56:50"))
        h = self.js(f"pvJobCard({json.dumps(j)},true)")
        for t in ("Training complete", "all 7 of 7 stages done", "Finished <b>2026-11-28 07:56", "Took <b>20 min 41 s", "New model <b>v002"):
            self.assertIn(t, h)
        self.assertNotIn("Stages left", h)

    def test_last_cycle_after_restart(self):
        h = self.js('pvJobCard({state:"idle",last_run:{state:"finished",started:"2026-11-28 07:36:08",finished:"2026-11-28 07:56:50",version:"v002"}},true)')
        self.assertIn("Last training cycle", h); self.assertIn("✓ complete", h); self.assertIn("v002", h)
        self.assertEqual(self.js('pvJobCard({state:"idle"},false)'), "")

    def test_server_fields(self):
        import percival_gui as PG
        saved = dict(PG.JOB)
        try:
            PG.JOB.clear(); now = time.time()
            PG.JOB.update(state="finished", stage="completed", started=now - 100, ended=now, heartbeat=now, progress=1.0, log=[], stage_times={k: now - 90 for k, _ in PG.STAGES})
            j = PG.job_state(); self.assertEqual(j["stages_done"], len(PG.STAGES)); self.assertIn("finished_at", j)
        finally:
            PG.JOB.clear(); PG.JOB.update(saved)


class FakeJournal:
    def __init__(self, jobs): self.jobs = jobs
    def list_jobs(self, states=None, limit=200):
        vals = {getattr(s, "value", s) for s in (states or [])}
        return [j for j in self.jobs if j["state"] in vals]


class FakePool:
    def __init__(self, jobs):
        self.jobs = jobs; self._svc = mock.Mock(); self._svc.journal = FakeJournal(jobs); self.paused = []
    def pause(self, jid):
        self.paused.append(jid)
        for j in self.jobs:
            if j["job_id"] == jid: j["state"] = "paused"
        return dict(job_id=jid, state="paused")


class TestEmergencyEject(unittest.TestCase):
    def setUp(self):
        import css_app; self.A = css_app; self.saved = dict(css_app.DRIVE)

    def tearDown(self): self.A.DRIVE.clear(); self.A.DRIVE.update(self.saved)

    def test_stops_all_transfers_then_unmounts(self):
        A = self.A
        jobs = [dict(job_id="j1", state="copying"), dict(job_id="j2", state="queued"), dict(job_id="j3", state="paused"), dict(job_id="j4", state="completed")]
        pool = FakePool(jobs); calls = []
        def ej(self_, **k): calls.append(k); return dict(ok=True, message="SAFE TO EJECT")
        from uengine.storage import EjectManager
        with mock.patch.object(A, "transfer_pool", return_value=pool), mock.patch.object(EjectManager, "eject_vault", ej):
            r = A.storage_post("emergency_eject", {"wait_s": 2})
        self.assertTrue(r["ok"]); self.assertEqual(sorted(pool.paused), ["j1", "j2"])          # every unfinished, not-yet-paused job
        self.assertTrue(calls and calls[0]["emergency"] is True and calls[0]["force"] is False)
        self.assertTrue(A.DRIVE["ejected"])                                                       # new drive work on hold
        with mock.patch("pensieve_move.due", side_effect=AssertionError("no move may start")):
            self.assertIsNone(A.pensieve_tick())

    def test_force_needs_the_server_token_flow(self):
        A = self.A; pool = FakePool([]); seen = []
        def ej(self_, **k): seen.append(k); return dict(ok=False, needs_force_confirmation=True, force_token="t", volume_name="Percival")
        from uengine.storage import EjectManager
        with mock.patch.object(A, "transfer_pool", return_value=pool), mock.patch.object(EjectManager, "eject_vault", ej):
            r = A.storage_post("emergency_eject", {"wait_s": 0}); self.assertTrue(r["needs_force_confirmation"])
            A.storage_post("emergency_eject", {"wait_s": 0, "force": True, "force_token": "t", "confirm_volume_name": "Percival"})
        self.assertEqual((seen[1]["force"], seen[1]["force_token"], seen[1]["confirm_volume_name"]), (True, "t", "Percival"))

    def test_button_on_every_screen(self):
        h = open(os.path.join(ROOT, "app", "css_app.html")).read()
        i = h.index('id="side-vault-emergency"'); self.assertLess(i, h.index('<div class="wrap" id="view">'))   # in the sidebar, not in a view
        self.assertIn("⏏ Emergency eject", h); self.assertIn('api("/api/storage/emergency_eject"', h)


if __name__ == "__main__":
    unittest.main()
