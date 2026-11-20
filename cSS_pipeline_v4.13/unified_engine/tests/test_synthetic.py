import unittest
import numpy as np
import _common  # noqa: F401
from uengine import synthetic as sy, math_component as mc


class TestSynthetic(unittest.TestCase):
    def test_labelled_synthetic_and_reproducible(self):
        a, e, p = sy.make_cohort(12, seed=9); b, _, _ = sy.make_cohort(12, seed=9)
        self.assertTrue(a.synthetic.all() and e.synthetic.all() and p.synthetic.all())
        self.assertTrue(a.patient_key.str.startswith("SYN").all() and a.exam_id.str.startswith("SYN").all())
        import pandas.testing as pt; pt.assert_frame_equal(a, b)

    def test_fates_come_from_the_verbatim_rules(self):
        O, E, P = sy.make_cohort(15, seed=2); E_ = {}
        for _, r in O[O.fate.isin(["shown", "rule_excluded"])].iterrows():
            ctx = mc.ScanContext(T1_ANAT=not r.missing_t1_anatomy); eng = E_.setdefault(ctx, mc.ExclusionEngine(ctx))
            self.assertEqual(eng.fate(r.to_dict())[0].split("@")[0], r.rule_id)

    def test_failed_registration_has_no_list_and_labels_follow_design(self):
        O, E, P = sy.make_cohort(40, seed=3, reg_fail_rate=0.3)
        failed = set(E.exam_id[E.registration == "failed"]); self.assertTrue(failed)
        self.assertFalse(set(O.exam_id) & failed)
        self.assertTrue(O.loc[O.fate == "shown", "y"].notna().all())
        self.assertTrue(O.loc[O.fate.isin(["gate_dropped", "not_generated"]), "y"].isna().all())
        ex = O[O.fate == "rule_excluded"]; self.assertTrue(ex.y.notna().any() and ex.y.isna().any())
        self.assertTrue(ex.loc[ex.rule_id == "E1", "y"].isna().all())          # E1 never in the audit sample

    def test_pure_noise_has_no_class_signal_in_any_column(self):
        """signal = 0: EVERY numeric column (not only the Gaussian ones) and every categorical column is independent of the truth.
        (Regression test: an earlier generator built struct_cls / struct_s2_mm / zone shares from the true class regardless of signal,
        which let the legacy confidence model reach AUC 1.00 on 'noise'.)"""
        from uengine import model_evaluation as ev
        O, _, _ = sy.make_cohort(80, seed=4, signal=0.0, negative_share=0.0, prevalence=("fixed", 0.4), gate_drop=(0, 1))
        C = O[O.measurement_complete].reset_index(drop=True); y = C.y_true.to_numpy()
        skip = {"y_true", "y", "obj_index", "synthetic", "measurement_complete", "missing_t1_anatomy"}
        for c in C.columns:
            if c in skip or C[c].dtype == object or str(C[c].dtype).startswith(("str", "string")): continue
            x = C[c].to_numpy(float); ok = np.isfinite(x)
            if ok.sum() < 50 or np.nanstd(x) == 0: continue
            a = ev.auc(y[ok], x[ok]); self.assertLess(abs(a - 0.5), 0.07, f"{c}: AUC {a:.3f} on pure noise")
        for c in ("struct_cls", "region"):
            tab = C.groupby(c).y_true.mean(); n = C.groupby(c).size()
            for k in tab.index[n >= 40]: self.assertLess(abs(tab[k] - y.mean()), 0.1, f"{c}={k}")
        m = __import__("uengine.ml_component", fromlist=["x"])
        sh = C[C.fate == "shown"].reset_index(drop=True); half = sh.patient_key.isin(sorted(sh.patient_key.unique())[::2])
        s = m.LegacyConfidence().fit(sh[half].reset_index(drop=True), sh.y_true[half].to_numpy(), sh.patient_key[half].to_numpy()).score(sh[~half])
        self.assertLess(abs(ev.auc(sh.y_true[~half].to_numpy(), s) - 0.5), 0.1)


if __name__ == "__main__":
    unittest.main()
