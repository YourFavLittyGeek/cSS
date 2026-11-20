"""feature / label / partition leakage, including repeat examinations and historical model outputs"""
import unittest
import numpy as np, pandas as pd
import _common  # noqa: F401
from uengine import data_validation as dv, ml_component as ml, synthetic as sy, characteristics_component as cc, feature_schema as fs
from uengine import patient_split as ps, model_evaluation as ev


class TestLeakage(unittest.TestCase):
    def test_forbidden_predictors_refused(self):
        with self.assertRaises(dv.LeakageError): dv.assert_predictors_allowed(fs.INITIAL_COLUMNS + ["confidence_pct"])
        with self.assertRaises(dv.LeakageError): dv.assert_predictors_allowed(["darkness_z", "score_v4"])
        with self.assertRaises(dv.LeakageError): dv.assert_predictors_allowed(["darkness_z", "my_pred_prob"])
        dv.assert_predictors_allowed(fs.INITIAL_COLUMNS)

    def test_label_copy_detected(self):
        O, _, _ = sy.make_cohort(15, seed=1, leak="label_copy"); sh = O[O.fate == "shown"]
        f = dv.near_perfect_separation(sh[["leaky_feature", "darkness_z"]].to_numpy(), sh.y.to_numpy(), ["leaky_feature", "darkness_z"])
        self.assertEqual([x["column"] for x in f], ["leaky_feature"])

    def test_copied_model_output_detected(self):
        O, _, _ = sy.make_cohort(15, seed=2, leak="model_output")
        f = dv.derived_from_model_output(O, ["copied_conf", "darkness_z"])
        self.assertEqual([x["predictor"] for x in f], ["copied_conf"])

    def test_test_labels_and_test_features_never_used_in_fitting(self):
        O, _, _ = sy.make_cohort(25, seed=3); sh = O[O.fate == "shown"].reset_index(drop=True)
        X, _ = cc.design_matrix(sh); y = sh.y.to_numpy(float); pid = sh.patient_key.to_numpy()
        a = ps.grouped_folds(pid, 5, 1, 0); tr, te = ps.fold_indices(a, pid, 0)[0]
        def fp(X_, y_, tr_, te_):
            return ml.PenalizedLogistic(fs.INITIAL_COLUMNS).fit_nested(X_[tr_], y_[tr_], pid[tr_], seed=0).predict(X_[te_])
        self.assertTrue(dv.test_label_invariance(fp, X, y, tr, te))
        def params(X_, y_, tr_):
            m = ml.PenalizedLogistic(fs.INITIAL_COLUMNS).fit_nested(X_[tr_], y_[tr_], pid[tr_], seed=0)
            return np.r_[m.beta, m.pre.median, m.pre.mean, m.pre.sd, m.lam]
        self.assertTrue(dv.preprocessing_isolation(params, X, y, tr, te))
        def fp_legacy(X_, y_, tr_, te_):
            d = sh.copy(); d["y"] = y_
            return ml.LegacyConfidence().fit(d.iloc[tr_], y_[tr_].astype(int), pid[tr_]).score(d.iloc[te_])
        self.assertTrue(dv.test_label_invariance(fp_legacy, X, y, tr, te))

    def test_partition_and_duplicates(self):
        self.assertTrue(dv.partition_disjoint(["A", "B"], ["B", "C"]))
        T = ps.ProtectedTestSet(("C",)); self.assertTrue(dv.partition_disjoint(["A", "C"], ["B"], T))
        O, _, _ = sy.make_cohort(6, seed=4); sh = O[O.fate == "shown"].copy()
        dup = sh.iloc[:3].copy(); dup["patient_key"] = "SYNP999"                 # an exam copied under another patient key
        self.assertTrue(dv.duplicate_objects(pd.concat([sh, dup])))
        self.assertFalse(dv.duplicate_objects(sh))

    def test_repeat_exam_leakage_is_real_and_prevented(self):
        """pure noise + near-identical repeat exams: a memorising 1-NN scorer looks excellent when exams of one patient are split
        across folds (exam-level CV) and is ~0.5 under patient-grouped CV"""
        r = np.random.default_rng(5); rows = []
        for p in range(30):
            base = r.normal(size=(12, 4)); yb = (r.random(12) < r.uniform(.2, .6)).astype(int)
            for e in range(2): rows += [dict(patient=f"SYNP{p}", exam=f"SYNP{p}-E{e}", y=yb[i], **{f"f{j}": base[i, j] + r.normal(0, .05) for j in range(4)}) for i in range(12)]
        D = pd.DataFrame(rows); X = D[[f"f{j}" for j in range(4)]].to_numpy(); y = D.y.to_numpy()
        def cv(groups):
            a = ps.grouped_folds(groups, 5, 1, 0); s = np.full(len(y), np.nan)
            for tr, te in ps.fold_indices(a, groups, 0):
                d = ((X[te, None, :] - X[None, tr, :]) ** 2).sum(-1); s[te] = y[tr][d.argmin(1)] + 1e-3 * r.random(len(te))
            return ev.auc(y, s)
        leaky, grouped = cv(D.exam.to_numpy()), cv(D.patient.to_numpy())
        self.assertGreater(leaky, 0.9); self.assertLess(abs(grouped - 0.5), 0.1)
        km = ps.PatientKeyMap.from_table(D.rename(columns=dict(exam="exam_id", patient="patient_key")).to_dict("records"))
        self.assertEqual(len(km.repeat_exams()), 30)

    def test_schema_ranges(self):
        df = pd.DataFrame(dict(cortex_frac=[0.5, 1.4, -0.1], volume_mm3=[10, -1, 5]))
        self.assertEqual(dv.schema_ranges(df), dict(cortex_frac=2, volume_mm3=1))


if __name__ == "__main__":
    unittest.main()
