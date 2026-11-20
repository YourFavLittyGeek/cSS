"""unit tests of the three prototype components and the input validation"""
import unittest
import numpy as np, pandas as pd
import _proto_fixtures as fx
from uengine import math_component as mc
from uengine.prototype.components import MathComponent, CharacteristicsComponent, IncrementComponent, NullPastExperience
from uengine.prototype.inputs import sanitize, InputError


class TestMathComponent(unittest.TestCase):
    def test_recorded_is_authoritative_and_verbatim_when_absent(self):
        m = MathComponent(); r = fx.row("cSS")
        o = m.outputs(r); self.assertEqual((o["source"], o["status"], o["score_v4"]), ("recorded", "ok", r["score_v4"]))
        r2 = dict(r); r2.pop("score_v4"); o2 = m.outputs(r2)
        self.assertEqual(o2["source"], "computed_verbatim"); self.assertAlmostEqual(o2["score_v4"], mc.score_v4(r2))

    def test_inconsistent_and_not_scorable(self):
        m = MathComponent()
        self.assertEqual(m.outputs(dict(fx.row("cSS"), score_v4=9.9))["status"], "inconsistent")
        self.assertEqual(m.outputs(dict(fx.row("cSS", score_v4=np.nan), darkness_z=np.nan))["status"], "not_scorable")
        self.assertEqual(m.outputs(dict(fx.row("cSS"), score_v4=-1.0))["status"], "not_scorable")
        self.assertEqual(m.outputs(dict(fx.row("cSS"), score_v4="abc", darkness_z="x"))["status"], "not_scorable")

    def test_regression_against_verbatim_on_synthetic_rows(self):
        tr, te, O, E, P = fx.cohort(); m = MathComponent(); eng = {}
        for r in pd.concat([tr, te]).head(400).to_dict("records"):
            o = m.outputs(r); self.assertEqual(o["source"], "recorded"); self.assertNotEqual(o["status"], "inconsistent")
            self.assertAlmostEqual(o["score_v4"], r["score_v4"])
            ctx = mc.ScanContext(T1_ANAT=not r["missing_t1_anatomy"]); e = eng.setdefault(ctx, mc.ExclusionEngine(ctx))
            self.assertEqual(o["rule_fate"], e.fate(r)[0].split("@")[0])

    def test_recalibration_monotone(self):
        tr, *_ = fx.cohort(); m = MathComponent().fit(tr.score_v4, tr.y)
        s = np.sort(tr.score_v4.to_numpy()); self.assertTrue(np.all(np.diff(m.recal.logit(s)) >= 0))


class TestCharacteristics(unittest.TestCase):
    def test_status_clip_and_corrupt(self):
        c = CharacteristicsComponent(); tr, *_ = fx.cohort()
        X = np.array([c.outputs(r)[1] for r in tr.to_dict("records")]); c.fit(X)
        o, x = c.outputs(fx.row("cSS", darkness_z=500.0))
        self.assertEqual(o["status"]["darkness_z"], "extrapolation_clipped"); self.assertLessEqual(x[0], c.hi[0])
        o, _ = c.outputs(fx.row("cSS"), {"edge_contrast": "corrupt"}); self.assertEqual(o["status"]["edge_contrast"], "corrupt")
        o, x = c.outputs(fx.row("cSS", tram_frac=np.nan, cortex_frac=np.nan, tube_ratio=np.nan))
        self.assertEqual(o["n_missing_or_invalid"], 2); self.assertEqual(o["values"]["tram_frac_missing"], 1.0)   # tram is structural


class TestLearned(unittest.TestCase):
    def test_offset_increment_and_contributions(self):
        r = np.random.default_rng(0); n = 1500; X = r.normal(size=(n, 3)); off = 1.5 * X[:, 0]
        y = (r.random(n) < 1 / (1 + np.exp(-off))).astype(float); pid = np.repeat([f"SYN{i}" for i in range(30)], 50)
        inc = IncrementComponent(["a", "b", "c"], offset=True).fit(X, y, pid, off)
        self.assertLess(np.abs(inc.m.beta[1:]).max(), 0.2)                 # information already in the offset is not learned again
        L, C, b0 = inc.increment(X); np.testing.assert_allclose(L, b0 + C.sum(1))
        j = IncrementComponent(["a", "b", "c"], offset=False, joint=True).fit(X, y, pid, off); self.assertEqual(j.m.columns[-1], "math_logit")
        self.assertTrue(np.all(NullPastExperience().increment(X)[0] == 0))


class TestInputs(unittest.TestCase):
    def test_sanitize(self):
        d = fx.frame([fx.row("cSS", 0), fx.row("vein", 1, darkness_z="bad", cortex_frac=1.8, edge_contrast=np.inf, tube_ratio=True)])
        c, rep = sanitize(d)
        self.assertEqual(rep.corrupt, {"darkness_z": 1, "edge_contrast": 1}); self.assertEqual(rep.out_of_range, {"cortex_frac": 1})
        self.assertTrue(np.isnan(c.darkness_z[1])); self.assertEqual(c.tube_ratio[1], 1.0)
        with self.assertRaises(InputError): sanitize(fx.frame([fx.row("cSS", 0), fx.row("vein", 0)]))         # duplicate key
        with self.assertRaises(InputError): sanitize(d.drop(columns=["exam_id"]))
        with self.assertRaises(InputError): sanitize(d, data_kind="clinical")
        with self.assertRaises(InputError): sanitize(d.assign(patient_key="M02"))
        with self.assertRaises(InputError): sanitize(d.assign(synthetic=False))
        with self.assertRaises(InputError): sanitize([1, 2])
        e, rep = sanitize(d.iloc[:0]); self.assertEqual(len(e), 0)


if __name__ == "__main__":
    unittest.main()
