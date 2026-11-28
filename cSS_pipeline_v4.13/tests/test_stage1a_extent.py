"""2026-11-28 Stage 1a (user decision): the full extent is the candidate's main outline ("one unit"), the ridge core stays inside it; the
reviewer rates the outline (OK / too small / too large / wrong shape). Safeguards tested: the detector's files and the calls are never
changed (the rating is a separate, append-only outline-quality record), blinded ids are mapped, the extent volume is detector geometry
(allowed in the blind read), the summary never becomes a label. Temporary folders only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)
H = open(os.path.join(ROOT, "scripts", "review_web.html")).read()


class TestRating(unittest.TestCase):
    def setUp(self):
        import review_web as RW
        self.RW = RW; self.b = tempfile.mkdtemp(prefix="s1a_"); os.makedirs(os.path.join(self.b, "review"))
        self.pb = mock.patch.object(RW, "B", self.b); self.pb.start()
        st = RW.Study.__new__(RW.Study); st.sid = "S1"; st.df = pd.DataFrame(dict(cand_id=[1, 2], volume_mm3=[30.0, 40.0]))
        st._ext = object(); st._ext_rec = dict(version="albus-extent/1.0", inputs=dict(cand="abc"), measures={"1": dict(extent_mm3=120.0, core_mm3=30.0, leak_warning=False)})
        self.st = st

    def tearDown(self): self.pb.stop()

    def test_append_only_separate_from_calls(self):
        st = self.st
        self.assertEqual(st.rate_outline("Dr A", 1, "too_small"), {1: "too_small"})
        self.assertEqual(st.rate_outline("Dr A", 1, "ok"), {1: "ok"})                     # latest wins, history kept
        lines = open(st.opath("Dr A")).read().strip().split("\n"); self.assertEqual(len(lines), 2)
        e = json.loads(lines[-1]); self.assertEqual((e["extent_version"], e["extent_mm3"], e["core_mm3"]), ("albus-extent/1.0", 120.0, 30.0))
        self.assertEqual(st.rate_outline("Dr A", 1, ""), {})                               # cleared
        self.assertFalse([f for f in os.listdir(os.path.join(self.b, "review")) if "_calls" in f])   # no call file touched
        with self.assertRaises(self.RW.RB.BlindError): st.rate_outline("Dr A", 1, "great")
        with self.assertRaises(self.RW.RB.BlindError): st.rate_outline("Dr A", 99, "ok")

    def test_routes_and_blinding(self):
        self.assertEqual(self.RW.ROUTES[("POST", "/api/outline")], "write")
        src = open(os.path.join(ROOT, "scripts", "review_web.py")).read()
        self.assertIn('cid = ctx.to_true(d.get("cand_id", 0)); r_ = s.rate_outline(rev, cid', src)
        import review_blind as RB
        ctx = mock.Mock(); ctx.to_blind.side_effect = lambda i: i + 100
        c = RB.redact_cand(dict(id=1, volume=30.0, ext_volume=120.0, ext_leak=True, centre=[1, 2, 3], vox=[1, 2, 3], feat={}), ctx)
        self.assertEqual((c["id"], c["ext_volume"], c["ext_leak"]), (101, 120.0, True))


class TestViewer(unittest.TestCase):
    def test_one_unit_outline(self):
        self.assertIn("PR=extMain()?EXT:LAB", H)                                         # the extent is the outline when it exists
        self.assertIn("if(PR===EXT&&LAB&&showCore&&showMark&&LAB[q]===curId", H)          # the core is drawn inside it
        self.assertIn('core:{l:"Show the ridge core inside (dotted)"', H); self.assertIn('ext:{l:"Outline = full extent (one unit)"', H)
        for r in ("ok", "too_small", "too_large", "wrong"): self.assertIn(f'data-orate="{r}"', H)
        self.assertIn('api("/api/outline"', H); self.assertIn("extMain()&&c.ext_volume!=null?c.ext_volume:c.volume", H)


class TestSummary(unittest.TestCase):
    def test_quality_summary(self):
        import percival_gui as PG
        b = tempfile.mkdtemp(prefix="s1aq_"); os.makedirs(os.path.join(b, "review"))
        rows = [dict(study="S1", reviewer="A", cand_id=1, rating="too_small"), dict(study="S1", reviewer="A", cand_id=1, rating="ok"),
                dict(study="S1", reviewer="A", cand_id=2, rating="too_large", leak_warning=True), dict(study="S2", reviewer="A", cand_id=1, rating="ok")]
        with open(os.path.join(b, "review", "S1_outline_by_A.jsonl"), "w") as f: f.write("\n".join(json.dumps(r) for r in rows[:3]) + "\n")
        with open(os.path.join(b, "review", "S2_outline_by_A.jsonl"), "w") as f: f.write(json.dumps(rows[3]) + "\n")
        with mock.patch.object(PG, "B", return_value=b): Q = PG.outline_quality()
        self.assertEqual((Q["n"], Q["studies"], Q["counts"], Q["ok_pct"]), (3, 2, {"ok": 2, "too_large": 1}, 67))
        self.assertEqual(Q["with_leak_warning"], {"too_large": 1}); self.assertFalse(Q["ready_for_stage2"])


if __name__ == "__main__":
    unittest.main()
