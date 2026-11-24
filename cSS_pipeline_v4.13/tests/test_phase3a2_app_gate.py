"""Phase 3A.2 (main app): per-study AI outputs are withheld in the app until the study's independent blind read is complete.

Access paths checked: /api/results (Studies sheet, study detail, Results view) and the results workbook built from it; PERCIVAL Center
score / history (GET) and on-demand Percival / unified scoring (POST); the explicit, journaled release; the release recorded with every later
reviewer action. Sentinel AI values are planted and searched for in the replies. Synthetic, in-process app on the isolated CSS_BASE."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import io
import json
import os
import sys
import threading
import unittest
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "scripts"), os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
import css_app                                                            # noqa: E402
import blind_gate as BG                                                   # noqa: E402
import review_io as RIO                                                   # noqa: E402

SENT_AI = 3.25                                                           # sentinel AI score value (written as 3.25)
SENT_MODEL = "SENTINEL_PCV_MODEL"


def _w(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: json.dump(obj, f)


class TestAppBlindGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = css_app.B; cls.codes = []; os.makedirs(os.path.join(cls.B, "review"), exist_ok=True)
        css_app.pg_init()                                                  # what the app does at start (Percival context)
        srv = css_app.ThreadingHTTPServer(("127.0.0.1", 0), css_app.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start(); cls.srv = srv
        cls.base = f"http://127.0.0.1:{srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close(); css_app.transfer_pool_shutdown(5)

    def setUp(self):
        self.code = f"G{len(self.codes) + 1:03d}"; self.codes.append(self.code); c = self.code; B = self.B
        css_app.PAT.append(dict(code=c, status="done", cohort="", mode="", uscore=dict(css_compatible=7, uncertain=5, alternative_high_confidence=1, model=True),
                                uscore_status="completed", ai_note=""))
        import pandas as pd
        pd.DataFrame([dict(cand_id=1, vox_i=1, vox_j=1, vox_k=1, volume_mm3=9.0, hemi="L", region="x")]).to_csv(f"{B}/review/{c}_candidates.csv", index=False)
        _w(f"{B}/review/{c}_score_ai.json", dict(L_score=1.25, R_score=2.0, multifocality_0_4=SENT_AI))
        _w(css_app.PG.P("scores", f"{c}.json"), dict(model=SENT_MODEL, run="r1", study_score=dict(total=SENT_AI)))

    def tearDown(self):
        css_app.PAT[:] = [p for p in css_app.PAT if p["code"] != self.code]

    # helpers
    def row(self): return next(r for r in css_app.results() if r["code"] == self.code)
    def http(self, path, body=None):
        r = urllib.request.Request(self.base + path, None if body is None else json.dumps(body).encode(),
                                   {"Content-Type": "application/json", "X-CSS-App": "1"} if body is not None else {})
        with urllib.request.urlopen(r, timeout=60) as h: return h.read()
    def journal(self, who, kind, **kw):
        with RIO.study_lock(self.B, self.code): RIO.journal_append(self.B, self.code, who, kind, **kw)
    def complete(self, who="Reader A"):
        self.journal(who, "blind_ids", assign={}); self.journal(who, "initial_completed", n_candidates=1, n_called=1)

    def assert_hidden(self):
        r = self.row()
        for k in BG.RESULT_AI_KEYS: self.assertNotIn(k, r)
        self.assertTrue(r["ai_hidden"]); self.assertNotEqual(r["label"], "AI only, not validated"); self.assertEqual(r["unified_status"], "hidden")
        body = self.http("/api/results").decode()
        mine = [x for x in json.loads(body) if x["code"] == self.code][0]
        self.assertNotIn("3.25", json.dumps(mine)); self.assertNotIn("1.25", json.dumps(mine))
        sc = json.loads(self.http(f"/api/percival/score?code={self.code}")); self.assertTrue(sc.get("hidden")); self.assertNotIn(SENT_MODEL, json.dumps(sc))
        self.assertTrue(json.loads(self.http(f"/api/percival/history?code={self.code}")).get("hidden"))
        for op, key in (("score", "code"), ("score_unified", "study_id")):
            r2 = json.loads(self.http(f"/api/percival/{op}", {key: self.code})); self.assertTrue(r2.get("hidden"), (op, r2))

    def assert_visible(self):
        r = self.row(); self.assertEqual(r.get("ai_total"), SENT_AI); self.assertEqual(r.get("unified_css_compatible"), 7); self.assertNotIn("ai_hidden", r)
        self.assertIn(SENT_MODEL, self.http(f"/api/percival/score?code={self.code}").decode())
        self.assertFalse(json.loads(self.http(f"/api/percival/history?code={self.code}")).get("hidden"))
        self.assertFalse(json.loads(self.http("/api/percival/score", {"code": self.code})).get("hidden"))

    # tests
    def test_before_any_blind_read_every_ai_path_is_withheld(self):
        self.assertEqual(BG.state(self.B, self.code)["status"], "pending")
        self.assert_hidden()
        self.assertEqual(json.loads(self.http(f"/api/blind/state?code={self.code}"))["status"], "pending")

    def test_results_workbook_is_masked_too(self):
        import pandas as pd
        df = pd.read_excel(io.BytesIO(css_app.export_xlsx()), sheet_name="results")
        mine = df[df.code == self.code]
        self.assertFalse(any(c in mine.columns and mine[c].notna().any() for c in ("ai_total", "ai_L", "ai_R", "unified_css_compatible")))

    def test_after_a_completed_blind_read_normal_display_returns(self):
        self.complete(); self.assertEqual(BG.state(self.B, self.code)["status"], "complete")
        self.assert_visible()

    def test_a_second_blind_read_in_progress_withholds_again(self):
        self.complete("Reader A"); self.journal("Reader B", "blind_ids", assign={})
        st = BG.state(self.B, self.code); self.assertEqual((st["status"], st["open_reads"]), ("pending", ["Reader B"]))
        self.assert_hidden()

    def test_a_review_finished_before_phase_3a_counts_as_complete(self):
        _w(f"{self.B}/review/{self.code}_final_Old_Reader.json", dict(reviewer="Old Reader"))
        self.assertEqual(BG.state(self.B, self.code)["status"], "complete")
        self.assert_visible()

    def test_release_needs_typed_confirmation_and_reason_and_is_journaled(self):
        self.assertFalse(json.loads(self.http("/api/blind/release", dict(code=self.code, by="me", reason="x", confirm="yes")))["ok"])
        self.assertFalse(json.loads(self.http("/api/blind/release", dict(code=self.code, by="me", reason="", confirm=BG.CONFIRM)))["ok"])
        self.assert_hidden()
        r = json.loads(self.http("/api/blind/release", dict(code=self.code, by="me", reason="clinical research question", confirm=BG.CONFIRM)))
        self.assertTrue(r["ok"]); self.assertEqual(r["state"]["status"], "released")
        self.assert_visible()
        ev, probs = RIO.read_journal(RIO.journal_path(self.B, self.code, BG.RELEASE_REVIEWER))
        self.assertEqual(probs, []); self.assertEqual((ev[-1]["kind"], ev[-1]["by"], ev[-1]["reason"]), ("ai_released", "me", "clinical research question"))

    def test_a_release_is_recorded_with_every_later_reviewer_action(self):
        import review_blind as RB
        self.assertFalse(RB.released_in_app(self.B, self.code))
        self.http("/api/blind/release", dict(code=self.code, by="me", reason="r", confirm=BG.CONFIRM))
        self.assertTrue(RB.released_in_app(self.B, self.code))
        src = open(os.path.join(ROOT, "scripts", "review_web.py")).read()
        self.assertIn("ai_released_in_app=ctx.released", src)              # carried into every journaled change of the reviewer

    def test_fail_closed(self):
        with mock.patch.object(BG, "_mods", return_value=None):
            self.assertTrue(BG.state(self.B, self.code)["pending"])
        self.complete()
        self.assertTrue(BG.state(self.B, "../evil")["pending"])

    def test_gui_shows_the_hidden_state_and_offers_the_recorded_release(self):
        html = open(os.path.join(ROOT, "app", "css_app.html")).read(); pv = open(os.path.join(ROOT, "app", "percival_view.js")).read()
        self.assertEqual(html.count("r.ai_hidden?"), 3)                     # Results view, Studies sheet, study detail
        self.assertIn('api("/api/blind/release"', html); self.assertIn("RELEASE AI RESULTS", html)
        self.assertIn('data-pv="hidden"', pv)


if __name__ == "__main__":
    unittest.main()
