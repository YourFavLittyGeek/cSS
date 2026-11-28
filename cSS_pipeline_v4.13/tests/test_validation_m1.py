"""2026-11-28 Milestone 1 (audit 2026-11-27, ~/PERCIVAL_audit_2026-11-27/03): validation methodology.
- stratified patient folds; discrimination measured WITHIN held-out folds (the v001 pooled AUC 0.508 came from mixing fold-specific models);
- paired model choice (the simplest model only when it is indistinguishable from the best) + 'informative' flag;
- within-fold calibration slope, never reversed;
- like-for-like acceptance (ALBUS on the same candidates), patient- and lesion-level test metrics;
- every test consultation uses the milestone; the readiness gate blocks training; SHADOW reads the real manifest shape.
Synthetic only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)
from uengine.percival import validation as V          # noqa: E402
from uengine.percival import meta as MT               # noqa: E402


def cohort(n_pat=40, seed=0, signal=1.0, pos_frac=0.4):
    """candidates of n_pat patients; cSS patients have 1-8 positives; score = signal * y + noise + a patient offset"""
    r = np.random.default_rng(seed); y, g, s = [], [], []
    for i in range(n_pat):
        n = int(r.integers(3, 25)); k = int(r.integers(1, 9)) if r.random() < pos_frac else 0; k = min(k, n)
        yy = np.r_[np.ones(k), np.zeros(n - k)]; off = r.normal(0, 1.0)
        y += list(yy); g += [f"P{i:02d}"] * n; s += list(signal * yy + off + r.normal(0, 1, n))
    return np.array(y), np.array(g), np.array(s)


class TestFolds(unittest.TestCase):
    def test_stratified_grouped(self):
        y, g, _ = cohort()
        F = V.folds(g, 5, 0, y)
        seen = set()
        for tr, te in F:
            pt = set(g[te]); self.assertFalse(pt & set(g[tr])); self.assertFalse(pt & seen); seen |= pt
            self.assertGreater(y[te].sum(), 0)                                    # every fold gets cSS
        self.assertEqual(seen, set(g))
        pos = [y[te].sum() for _, te in F]; self.assertLessEqual(max(pos) - min(pos), 8)
        self.assertEqual([list(te) for _, te in V.folds(g, 5, 0, y)], [list(te) for _, te in F])       # deterministic

    def test_unstratified_unchanged_without_y(self):
        y, g, _ = cohort(); a = V.folds(g, 5, 3); b = MT.folds(g, 5, 3)
        self.assertEqual([list(t) for _, t in a], [list(t) for _, t in b])


class TestWithinFold(unittest.TestCase):
    def test_null_fixed_score_is_half(self):
        """a score with no signal and no learned direction: expected fold-AUC 0.5 (the pooled table of fold models was biased below)"""
        A = []
        for k in range(120):
            y, g, _ = cohort(seed=k); s = np.random.default_rng(1000 + k).normal(size=len(y))
            A.append(V.fold_auc(y, s, V.fold_ids(len(y), V.folds(g, 5, k, y))))
        self.assertAlmostEqual(float(np.mean(A)), 0.5, delta=0.03)

    def test_fold_offsets_do_not_hide_a_within_fold_ranking(self):
        """the v001 mechanism: every fold ranks correctly but each fold's model adds its own offset -> pooled AUC near 0.5"""
        y, g, s = cohort(seed=5, signal=1.5); F = V.folds(g, 5, 0, y); fid = V.fold_ids(len(y), F)
        shift = np.array([0.0, -6.0, 6.0, -3.0, 3.0])[fid]                       # fold-specific offsets (fold models)
        z = s + shift
        self.assertLess(V._auc(y, z), V.fold_auc(y, z, fid) - 0.1)
        self.assertAlmostEqual(V.fold_auc(y, z, fid), V.fold_auc(y, s, fid), places=9)
        c = V.calibrate(z, y, fid); self.assertFalse(c["clamped"]); self.assertGreater(c["b"], 0.3)


class TestSelection(unittest.TestCase):
    def test_better_model_wins_over_simpler_null(self):
        y, g, s = cohort(seed=2, signal=2.0); fid = V.fold_ids(len(y), V.folds(g, 5, 0, y))
        noise = np.random.default_rng(9).normal(size=len(y))
        ch, rep, inf = V.select_kind({"simple": noise, "complex": s}, y, fid, g, ["simple", "complex"])
        self.assertEqual(ch, "complex"); self.assertTrue(inf); self.assertFalse(rep["simple"]["within_one_paired_se"])

    def test_simpler_kept_when_indistinguishable(self):
        y, g, s = cohort(seed=3, signal=2.0); fid = V.fold_ids(len(y), V.folds(g, 5, 0, y))
        s2 = s + np.random.default_rng(4).normal(0, 0.01, len(s))
        ch, _, inf = V.select_kind({"simple": s, "complex": s2}, y, fid, g, ["simple", "complex"]); self.assertEqual(ch, "simple"); self.assertTrue(inf)

    def test_noise_not_informative(self):
        y, g, _ = cohort(seed=4); fid = V.fold_ids(len(y), V.folds(g, 5, 0, y)); n = np.random.default_rng(5).normal(size=len(y))
        _, _, inf = V.select_kind({"a": n}, y, fid, g, ["a"]); self.assertFalse(inf)


class TestTrainCycle(unittest.TestCase):
    def rows(self, signal):
        y, g, s = cohort(n_pat=36, seed=11, signal=signal); r = np.random.default_rng(0); test = {f"P{i:02d}" for i in range(28, 36)}
        return [dict(study=f"S{p}", cand_id=int(i), patient=p, y=float(t), test=p in test, math=float(np.exp(v)),
                     char={c: float(v + r.normal(0, 0.5)) if j == 0 else float(r.normal()) for j, c in enumerate(MT.CHAR)}, maps=None)
                for i, (t, p, v) in enumerate(zip(y, g, s))]

    def test_signal_informative_and_calibrated(self):
        M = MT.train_cycle(self.rows(2.0), "v900", cnn_epochs=0, nested=False)
        self.assertTrue(M["informative"]); self.assertFalse(M["calibration"]["clamped"]); self.assertGreater(M["calibration"]["b"], 0)
        self.assertEqual(M["discovery"]["method"], V.METHOD_VERSION); self.assertTrue(M["discovery"]["folds"]["shared_with_components"])
        t = M["test"]; self.assertIn("math_same", t); self.assertIn("patient_level", t); self.assertIn("lesion_level", t)
        self.assertEqual(t["math_same"]["n"], int(round(t["coverage"] * t["n"])))

    def test_no_signal_flagged(self):
        M = MT.train_cycle(self.rows(0.0), "v901", cnn_epochs=0, nested=False)
        if not M["informative"]:
            self.assertTrue(any("not informative" in x for x in MT.acceptance(M, None)["reasons"]))


class TestAcceptance(unittest.TestCase):
    def test_like_for_like_and_candidate_patients(self):
        t = dict(percival=dict(auc=0.80, auc_ci=[0.7, 0.9], calib_slope=1.0), math=dict(auc=0.70), math_same=dict(auc=0.85),
                 patient_classes=dict(with_css=5, without_css=5), candidate_css_patients=4, n=100)
        R = MT.acceptance(dict(test=t, ready=True, informative=True, calibration=dict(clamped=False), nested=None), None)["reasons"]
        self.assertTrue(any("below ALBUS alone 0.850 (same candidates)" in x for x in R))
        self.assertTrue(any("rests on 4 patients with a cSS candidate" in x for x in R))
        R2 = MT.acceptance(dict(test=t, ready=True, informative=False, calibration={}, nested=None), None)["reasons"]
        self.assertTrue(any("not informative" in x for x in R2))


class TestLevels(unittest.TestCase):
    def test_patient_level(self):
        y = np.array([1, 0, 0, 0, 0, 0.]); p = np.array([.9, .2, .8, .1, .3, .4]); g = np.array(["A", "A", "B", "C", "D", "D"])
        r = V.patient_level(y, p, g, extra_pos=["D"])                             # D: only an expert-marked missed cSS
        self.assertEqual((r["with_css"], r["without_css"]), (2, 2))
        self.assertAlmostEqual(r["auc"], 0.75)                                   # A .9, D .4 positive; B .8, C .1 negative -> 3 of 4 pairs
        th = V.at_threshold_patients(y, p, g, 0.5, ["D"]); self.assertEqual((th["tp"], th["fn"], th["fp"], th["tn"]), (1, 1, 1, 1))

    def test_lesion_level(self):
        y = np.array([1, 1, 0, 0, 0, 0.]); p = np.array([.9, .2, .8, .7, .1, .05]); st = ["S1", "S1", "S1", "S2", "S2", "S2"]
        r = V.lesion_level(y, p, st, n_missed=2, fp_per_study=(0.5, 1))
        self.assertEqual(r["n_lesions"], 4)                                       # 2 candidates + 2 missed by the detector
        self.assertEqual(r["points"][0]["sensitivity"], 0.25)                     # threshold .9: 1 TP, 0 FP
        self.assertEqual(r["points"][1]["sensitivity"], 0.5)                      # .2: 2 TP, 2 FP / 2 studies = 1.0 FP per study


class TestApp(unittest.TestCase):
    def setUp(self):
        import percival_gui as PG
        self.PG = PG; self.d = tempfile.mkdtemp(prefix="m1_")

    def test_failed_consultation_uses_the_milestone(self):
        PG = self.PG; log = os.path.join(self.d, "split", "test_consultations.jsonl")
        plan = dict(version=1, registered_by="x", milestones=[dict(id="M2", name="x")])
        cons = lambda: [json.loads(l) for l in open(log)] if os.path.exists(log) else []
        with mock.patch.object(PG, "evaluation_plan", return_value=plan), mock.patch.object(PG, "test_consultations", side_effect=cons), \
             mock.patch.object(PG, "P", side_effect=lambda *a: os.path.join(self.d, *a)):
            M = dict(version="v002", test=dict(n=10, percival=dict(auc=0.6)))
            a1 = PG.test_reuse_gate(M, dict(reasons=["test AUC below ALBUS alone"]), ["p1", "p2"])
            self.assertFalse(a1["test_consultation"]["used_for_acceptance"]); self.assertTrue(a1["test_consultation"]["consumed"])
            a2 = PG.test_reuse_gate(dict(M, version="v003"), dict(reasons=[]), ["p1", "p2"])
            self.assertFalse(a2["passed"]); self.assertTrue(any("already consulted at milestone M2" in x for x in a2["reasons"]))

    def test_gate_blocks_training(self):
        PG = self.PG
        R = dict(training_permitted=False, stages=[dict(stage="ground truth available", ok=False, detail="development 1 cSS / 2 not-cSS", blocks=True)])
        saved = dict(PG.JOB)
        try:
            PG.JOB.update(state="idle")
            with mock.patch.dict(os.environ, {"CSS_TRAIN_GATE": "off"}), mock.patch.object(PG, "readiness", return_value=R), \
                 mock.patch.object(PG.threading, "Thread", side_effect=AssertionError("must not start")):
                r = PG.train_async("t")
            self.assertFalse(r["ok"]); self.assertEqual(r["stage"], "readiness_gate"); self.assertIn("ground truth available", r["error"])
            self.assertEqual(PG.JOB["state"], "idle")
        finally:
            PG.JOB.clear(); PG.JOB.update(saved)

    def test_shadow_reads_the_real_manifest_shape(self):
        PG = self.PG; os.makedirs(os.path.join(self.d, "review"))
        with open(os.path.join(self.d, "review", "S1_candidates.csv"), "w") as f: f.write("cand_id,volume_mm3,darkness_z\n1,30,-3\n2,40,-2\n3,50,-1\n")
        ex = [dict(study="S1", cand_id=1, patient="P1", y=1, partition="development", components=dict(shadow=True)),
              dict(study="S1", cand_id=2, patient="P1", y=0, partition="development", components=dict(shadow=True)),
              dict(study="S1", cand_id=3, patient="P1", y=0, partition="development", components=dict(shadow=False))]   # no 'status' key
        ids = mock.Mock(); ids.check_rows.return_value = []; ids.partition.return_value = "development"
        from uengine.percival import datasets as DS
        with mock.patch.object(DS, "listing", return_value=[dict(id="ds001")]), mock.patch.object(DS, "load", return_value=dict(id="ds001", examples=ex)), \
             mock.patch.object(PG, "B", return_value=self.d), mock.patch.object(PG, "IDS", return_value=ids), \
             mock.patch.object(PG, "gather", return_value=[]):
            rows = PG._shadow_rows()
        rows = rows[0] if isinstance(rows, tuple) else rows
        self.assertEqual(sorted(r["cand_id"] for r in rows), [1, 2])


if __name__ == "__main__":
    unittest.main()
