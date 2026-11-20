import unittest
import _common  # noqa: F401
from uengine import patient_split as ps, synthetic as sy


class TestSplit(unittest.TestCase):
    def setUp(self):
        self.O, self.E, self.P = sy.make_cohort(40, seed=3, repeat_rate=0.8)
        self.km = ps.PatientKeyMap.from_table(self.E.to_dict("records"))

    def test_repeat_exams_exist_and_stay_together(self):
        rep = self.km.repeat_exams(); self.assertGreater(len(rep), 5)
        sh = self.O[self.O.fate == "shown"]
        pats = self.km.patients(sh.exam_id)
        a = ps.grouped_folds(pats, 5, 3, seed=11, patient_label=dict(zip(self.P.patient_key, self.P.positive)))
        for r in range(3):
            for tr, te in ps.fold_indices(a, pats, r):
                self.assertFalse(set(pats[tr]) & set(pats[te]))
                ex_te = set(sh.exam_id.iloc[te])
                for p, exs in rep.items():                       # every exam of a patient in the same part
                    inside = [e in ex_te for e in exs if e in set(sh.exam_id)]
                    self.assertTrue(all(inside) or not any(inside))

    def test_refuses_without_mapping_and_records_assumption(self):
        with self.assertRaises(ps.SplitError): ps.keymap_or_refuse(["A", "B"])
        km = ps.keymap_or_refuse(["A", "B"], assume_one_exam_per_patient=True)
        self.assertFalse(km.verified); self.assertIn("UNVERIFIED", km.note)
        with self.assertRaises(ps.SplitError): ps.PatientKeyMap.from_table([dict(exam_id="A", patient_key="1"), dict(exam_id="A", patient_key="2")])
        with self.assertRaises(ps.SplitError): self.km.patients(["SYN-UNKNOWN"])

    def test_protected_test_set(self):
        T = ps.ProtectedTestSet(("SYNP000", "SYNP001"))
        with self.assertRaises(ps.SplitError): ps.grouped_folds(self.P.patient_key, 5, protected=T)
        dev = [p for p in self.P.patient_key if p not in T.patients]
        a = ps.grouped_folds(dev, 5, protected=T); self.assertEqual(a.protected, T.sha256)
        with self.assertRaises(ps.SplitError): ps.ProtectedTestSet(("SYNP000",), sha256=T.sha256)   # edited list, old hash

    def test_reproducible_and_seed_dependent(self):
        p = list(self.P.patient_key)
        self.assertEqual(ps.grouped_folds(p, 5, 2, 7).digest(), ps.grouped_folds(p, 5, 2, 7).digest())
        self.assertNotEqual(ps.grouped_folds(p, 5, 1, 7).digest(), ps.grouped_folds(p, 5, 1, 8).digest())
        t = ps.grouped_folds(p, 5, 2, 7).table(); self.assertEqual(len(t), 2 * len(p))

    def test_stratification(self):
        lab = dict(zip(self.P.patient_key, self.P.positive))
        a = ps.grouped_folds(list(lab), 5, 1, 0, lab)
        for f in range(5):
            labs = {lab[p] for (r, p), ff in a.folds.items() if ff == f}
            self.assertEqual(labs, {0, 1})


if __name__ == "__main__":
    unittest.main()
