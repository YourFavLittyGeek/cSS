"""2026-11-26 follow-up of docs/AUDIT_pipeline_2026-11-26.md (verified against the code first):
A1 the PERCIVAL study grade uses the model's own calibrated bands (green = likely -> total, green + yellow = possible -> total_upper), not a
   fixed 50; candidates PERCIVAL holds back for expert review make the study 'needs_review' (lower bound), never a silent negative;
A2 one AI opinion: the reviewer and the Results table show the PERCIVAL grade when it exists, the rule meter only labelled as a fallback;
   the new result fields are withheld during a blind read;
A3 legacy albus.py: 'threshold_before' is the value before the update; one patient with many misses no longer moves the threshold more
   than the same misses spread over several patients.
Synthetic only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "scripts"), os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)
NODE = shutil.which("node"); HTML = os.path.join(ROOT, "scripts", "review_web.html")


class Mem:
    def __init__(self, missed, fp=()): self.m, self.fp = list(missed), list(fp)
    def ask_albus_memory(self, limit=100): return dict(missed_lesions_count=len(self.m), missed_lesions=self.m, false_positive_corrections=self.fp)
    def record_correction(self, **k): return "c1"
    def get_study(self, sid): return {}


class TestLegacyAlbus(unittest.TestCase):
    def test_normalisation_and_threshold_before(self):
        from uengine.albus import AlbusDiscoveryEngine as A
        one = A(threshold=0.5, pensieve=Mem([dict(study_id="P1")] * 12)); one.update_adaptive_threshold()
        spread = A(threshold=0.5, pensieve=Mem([dict(study_id=f"P{i}") for i in range(12)])); spread.update_adaptive_threshold()
        self.assertGreater(one.threshold, spread.threshold)                     # one scan moves it LESS than 12 scans (was the opposite)
        self.assertGreater(one.threshold, 0.45)
        e = A(threshold=0.5, pensieve=Mem([dict(study_id="P1")]))
        ev = e.learn_from_missed_lesion("P1", (1, 2, 3), (1.0, 2.0, 3.0), dict(darkness_z=-2.0, pdist=0.2, tube_ratio=0.3))
        self.assertEqual(ev["threshold_before"], 0.5); self.assertLess(ev["threshold_after"], 0.5)


class TestStudyGrade(unittest.TestCase):
    def run_grade(self, S):
        import percival_gui as PG
        calls = []
        def fake_run(cmd, **k):
            tag = cmd[cmd.index("--tag") + 1]; ids = cmd[cmd.index("--accept-ids") + 1]; calls.append((tag, ids))
            n = 0 if ids == "none" else len(ids.split(","))
            os.makedirs(os.path.join(PG.B(), "review"), exist_ok=True)
            json.dump(dict(L_score=min(n, 2), R_score=0, multifocality_0_4=min(n, 2)), open(os.path.join(PG.B(), "review", f"SG1_score_{tag}.json"), "w"))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        M = dict(version="v001", ready=False, note="", thresholds=dict(red_below=0.2, green_from=0.7))
        import uengine.percival.meta as MT, tempfile
        T = tempfile.mkdtemp(prefix="grade_")
        with mock.patch.object(PG, "B", return_value=T), mock.patch.object(PG, "P", side_effect=lambda *a: os.path.join(T, "percival", *a)), \
             mock.patch.object(PG, "_js", side_effect=lambda p, d: None), mock.patch.object(PG, "gather", return_value=[dict(cand_id=s["cand_id"]) for s in S]), mock.patch.object(MT, "score_rows", return_value=S), \
             mock.patch.object(PG.subprocess, "run", side_effect=fake_run), mock.patch.object(PG, "experimental_core_enabled", return_value=False), \
             mock.patch.object(PG, "confirmed_mark_rows", return_value=[]), mock.patch.dict(PG.CTX, {"SC": os.path.join(ROOT, "scripts")}), \
             mock.patch.object(PG, "_run_id", return_value="r1"):
            rec = PG.score_study("SG1", M)
        return rec["study_score"], calls

    def test_bands_not_fifty_and_review_counted(self):
        S = [dict(cand_id=1, percival_score=90.0, band="green", status="reliable"), dict(cand_id=2, percival_score=55.0, band="yellow", status="reliable"),
             dict(cand_id=3, percival_score=30.0, band="yellow", status="uncertain"), dict(cand_id=4, percival_score=None, band=None, status="review"),
             dict(cand_id=5, percival_score=10.0, band="red", status="reliable")]
        st, calls = self.run_grade(S)
        self.assertEqual(st["called_ids"], [1]); self.assertEqual(st["called_ids_upper"], [1, 2, 3])   # 55 is NOT likely (green_from 70); 30 is possible
        self.assertEqual((st["total"], st["total_upper"]), (1, 2)); self.assertEqual(calls, [("percival", "1"), ("percival_upper", "1,2,3")])
        self.assertEqual(st["status"], "needs_review"); self.assertEqual(st["review_ids"], [4]); self.assertIn("lower bound", st["reason"])
        self.assertEqual(st["cuts"]["green_from"], 0.7)

    def test_unassessable_and_single_run(self):
        st, calls = self.run_grade([dict(cand_id=1, percival_score=None, status="insufficient")])
        self.assertEqual(st["status"], "unassessable"); self.assertEqual(calls, [])
        st, calls = self.run_grade([dict(cand_id=1, percival_score=95.0, band="green", status="reliable")])
        self.assertEqual(st["status"], "scored"); self.assertEqual(st["total"], st["total_upper"]); self.assertEqual(len(calls), 1)


class TestOneOpinion(unittest.TestCase):
    def test_results_prefer_percival_and_blind_mask(self):
        import blind_gate as BG
        for k in ("ai_total_upper", "ai_source", "ai_status", "ai_model"): self.assertIn(k, BG.RESULT_AI_KEYS)
        src = open(os.path.join(ROOT, "app", "css_app.py")).read()
        self.assertIn('ai_source="Percival"', src); self.assertIn('r["ai_source"] = "rule meter"', src)

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_reviewer_chip(self):
        src = open(HTML).read(); i = src.index("function paintScores(){"); fn = src[i:src.index("function paintLists(){")]
        def chip(us, ai):
            code = ("let H={};const $=s=>(H[s]=H[s]||{innerHTML:''});const esc=x=>String(x);let vmode=false,finalRec=null,readerScore={multifocality_0_4:2};"
                    "const scoreCard=(a,b,c)=>a+'|'+c;" + f"let M={{percival:{json.dumps(us)},ai_score:{json.dumps(ai)},calls_rule:''}};" + fn +
                    "paintScores();process.stdout.write(JSON.stringify([H['#scorechip'].innerHTML,H['#scorecard'].innerHTML]))")
            r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
            if r.returncode: raise RuntimeError(r.stderr)
            return json.loads(r.stdout)
        c, card = chip(dict(model="v001", study_score=dict(total=1, total_upper=2, status="needs_review", n_called=1, n_called_upper=3, n_review=1)), dict(multifocality_0_4=3))
        self.assertIn("Percival", c); self.assertIn("1–2/4 ≥", c); self.assertNotIn("rule meter", c); self.assertNotIn("3/4", c)
        self.assertIn("need expert review", card)
        c, card = chip(None, dict(multifocality_0_4=3, n_green=2))
        self.assertIn("AI rule meter", c); self.assertIn("3/4", c); self.assertIn("not validated", card)


if __name__ == "__main__":
    unittest.main()
