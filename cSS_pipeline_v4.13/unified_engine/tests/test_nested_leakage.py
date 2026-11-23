"""v5.25 - leakage tests for the Percival learning engine (synthetic only).

The decisive property of an honest out-of-fold prediction: it must not change when the LABELS, FEATURES or IMAGES of the patients in its
own held-out fold change (except through that row's own inputs at prediction time, which these tests keep fixed where it matters).
  * component_oof: Fusion's held-out predictions must be invariant to the held-out fold's labels (the v5.24 indirect leak: the image
    out-of-fold logits of the training rows came from image models that had seen the held-out fold).
  * nested_crossfit: every fitted / selected quantity of an outer fold (families, meta-model, calibration, thresholds) and the held-out
    predictions must be invariant to the held-out patients' labels; fitted quantities also to their features and images.
  * patient identity: several examinations of one patient always fall on the same side; rows without a patient are refused.
Run: python -m unittest -v test_nested_leakage   (from unified_engine/tests)"""
import copy, unittest
import numpy as np
import _common  # noqa: F401
from uengine.percival import meta as MT, nested as NS
from uengine.percival.cnn import IN_SHAPE


def make_rows(n_pat=24, per=5, seed=0, exams=1, image_frac=1.0):
    """synthetic candidates: label depends on characteristics, predictors and a dark image core; a few patients have 2 examinations"""
    r = np.random.default_rng(seed); rows = []
    for p in range(n_pat):
        pat = f"P{p:03d}"; lev = r.normal()
        for e in range(exams if p % 4 == 0 else 1):
            sid = f"S{p:03d}_{e}"
            for c in range(per):
                y = float(r.random() < 1 / (1 + np.exp(-(lev + r.normal()))))
                ch = {k: float(r.normal(0.9 * y if i < 4 else 0, 1)) for i, k in enumerate(MT.CHAR)}
                pr = {k: float(r.normal(0.7 * y, 1)) for k in MT.PREDICTORS}
                maps = None
                if r.random() < image_frac:
                    maps = r.normal(size=IN_SHAPE).astype(np.float32)
                    if y: maps[0, 20:29, 9:16] -= 1.2
                rows.append(dict(study=sid, cand_id=c + 100 * e, patient=pat, y=y, math=float(np.exp(r.normal(0.8 * y, 1))), pred=pr, char=ch,
                                 maps=maps, test=False, qc=""))
    return rows


def flip_labels(rows, patients):
    out = copy.deepcopy(rows)
    for x in out:
        if x["patient"] in patients: x["y"] = 1.0 - x["y"]
    return out


def scramble_inputs(rows, patients, seed=9):
    r = np.random.default_rng(seed); out = copy.deepcopy(rows)
    for x in out:
        if x["patient"] in patients:
            x["char"] = {k: float(v * 50 + r.normal(0, 30)) for k, v in x["char"].items()}
            x["pred"] = {k: float(r.normal(0, 40)) for k in x["pred"]}
            x["math"] = float(r.exponential(50))
            if x["maps"] is not None: x["maps"] = (r.normal(size=IN_SHAPE) * 9).astype(np.float32)
    return out


EP = 4   # few CNN epochs: the property tested is structural, not accuracy


class TestFusionCrossFitting(unittest.TestCase):
    def test_fusion_heldout_invariant_to_heldout_labels(self):
        rows = make_rows(seed=1)
        g = np.array([r["patient"] for r in rows]); F = MT.folds(g, 5, 0)
        kinds = dict(char_kinds=["logistic"], image_kinds=["pixel_logistic"], fusion_kinds=["feature"])   # fixed: no family selection
        Z0, _ = MT.component_oof(rows, seed=0, cnn_epochs=EP, **kinds)
        for i, (tr, te) in enumerate(F[:3]):
            held = set(g[te]); Z1, _ = MT.component_oof(flip_labels(rows, held), seed=0, cnn_epochs=EP, **kinds)
            for c in ("char", "image", "fusion", "unified", "math"):
                a, b = Z0[c][te], Z1[c][te]; m = np.isfinite(a)
                self.assertTrue(np.array_equal(np.isfinite(a), np.isfinite(b)), c)
                np.testing.assert_allclose(a[m], b[m], rtol=0, atol=1e-9, err_msg=f"{c}: held-out fold {i} depends on its own labels")
            self.assertTrue(np.isfinite(Z0["fusion"][te]).any(), "fusion produced no held-out prediction - test would be vacuous")


class TestNestedCrossFit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = make_rows(n_pat=30, per=5, seed=2, exams=2)
        cls.rep0, cls.arr0 = NS.nested_crossfit(cls.rows, seed=0, cnn_epochs=EP, ablations=True)
        cls.g = np.array([r["patient"] for r in cls.rows])

    def test_outer_folds_partition_patients(self):
        seen = set()
        for tr, te in self.arr0["folds"]:
            self.assertFalse(set(self.g[tr]) & set(self.g[te]))
            self.assertFalse(set(self.g[te]) & seen); seen |= set(self.g[te])
        self.assertEqual(seen, set(self.g))

    def test_heldout_predictions_and_fitted_quantities_invariant_to_heldout_labels(self):
        for i in (0, 2):
            tr, te = self.arr0["folds"][i]; held = set(self.g[te])
            rep1, arr1 = NS.nested_crossfit(flip_labels(self.rows, held), seed=0, cnn_epochs=EP, ablations=True)
            f0, f1 = self.rep0["folds"][i], rep1["folds"][i]
            for k in ("families", "meta", "calibration", "thresholds", "train_hash"):
                self.assertEqual(f0[k], f1[k], f"fold {i}: {k} depends on the held-out labels")
            np.testing.assert_allclose(self.arr0["p"][te], arr1["p"][te], atol=1e-12, err_msg=f"fold {i}: held-out scores depend on own labels")
            for name in NS.ABLATIONS:
                a, b = self.arr0["ablation"][name][te], arr1["ablation"][name][te]
                np.testing.assert_allclose(a[np.isfinite(a)], b[np.isfinite(b)], atol=1e-9, err_msg=f"ablation {name}, fold {i}")

    def test_fitted_quantities_invariant_to_heldout_features_and_images(self):
        tr, te = self.arr0["folds"][1]; held = set(self.g[te])
        rep1, _ = NS.nested_crossfit(scramble_inputs(self.rows, held), seed=0, cnn_epochs=EP, ablations=False)
        for k in ("families", "meta", "calibration", "thresholds"):
            self.assertEqual(self.rep0["folds"][1][k], rep1["folds"][1][k], f"{k} fitted with held-out features / images")

    def test_report_is_complete_and_honest(self):
        r = self.rep0
        self.assertIn("not an independent or clinical validation", r["basis"])
        for k in ("candidates", "patients", "patients_with_css", "patients_without_css", "evaluable_folds"): self.assertIn(k, r["support"])
        self.assertIsNotNone(r["percival"].get("auc")); self.assertIn("at_red_cut", r["percival"])
        self.assertEqual(set(r["ablation"]), set(NS.ABLATIONS))
        self.assertIn("vs_percival", r["ablation"]["MATH alone"])


class TestPatientIdentity(unittest.TestCase):
    def test_rows_without_patient_refused(self):
        rows = make_rows(n_pat=12, seed=3); rows[0]["patient"] = None
        with self.assertRaises(ValueError): MT.check_partitions(rows)

    def test_patient_on_both_sides_refused(self):
        rows = make_rows(n_pat=12, seed=3, exams=2); first = [x for x in rows if x["patient"] == "P000"]
        first[0]["test"] = True
        with self.assertRaises(ValueError): MT.check_partitions(rows)

    def test_all_examinations_of_a_patient_in_one_partition(self):
        rows = make_rows(n_pat=40, seed=4, exams=3)
        for x in rows: x["test"] = MT.test_assignment(x["patient"])
        MT.check_partitions(rows)
        g = np.array([x["patient"] for x in rows])
        for tr, te in MT.folds(g, 5, 0): self.assertFalse(set(g[tr]) & set(g[te]))


if __name__ == "__main__":
    unittest.main()
