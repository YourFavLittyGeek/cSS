"""2026-11-26 balanced locked test group (user decision; audit recommendation 7) + patients with expert-marked missed cSS count as patients
with cSS in the acceptance check.
- balance never moves a test patient out, never moves a patient a model was trained on, never a patient without a finished review, keeps
  >= MIN_DEV_PER_CLASS development patients per class, picks in a fixed hash order (not by hand), writes a NEW split version only with
  the typed confirmation, a person and a reason; nothing to do -> refused;
- train_cycle: a test patient with an expert missed-cSS mark but no cSS candidate is counted 'with cSS'.
Temporary store only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)
from uengine.percival import split as SP, meta as MT        # noqa: E402
from test_lumos_missed_marks import rows_and_marks          # noqa: E402


def store_with(test_css, test_neg, dev_css, dev_neg):
    st = tempfile.mkdtemp(prefix="split_bal_")
    S = SP.create(st, 0.2, "test", "fixture", patients=[], carry_test=[f"TC{i}" for i in range(test_css)] + [f"TN{i}" for i in range(test_neg)])
    for i in range(dev_css): S["assignment"][f"DC{i}"] = "development"
    for i in range(dev_neg): S["assignment"][f"DN{i}"] = "development"
    SP._js(os.path.join(st, "split", f"{S['version']}.json"), S)
    cl = {p: ("css" if p[1] == "C" else "no_css") for p in S["assignment"]}
    return st, cl


class TestBalance(unittest.TestCase):
    def test_the_users_case(self):
        st, cl = store_with(5, 4, 11, 30)                    # 5 / 4 test, as in the user's project with 040 counted
        P = SP.balance_plan(st, cl)
        self.assertEqual(P["after"], dict(css=5, no_css=5)); self.assertEqual(list(P["add"].values()), ["no_css"])
        self.assertEqual(P["add"], SP.balance_plan(st, cl)["add"])                    # deterministic: hash order, not a choice
        with self.assertRaises(PermissionError): SP.balance(st, cl, "Dr A", "why", "yes")
        with self.assertRaises(SP.SplitError): SP.balance(st, cl, "", "why", SP.CONFIRM_BALANCE)
        S = SP.balance(st, cl, "Dr A", "pilot: too few test patients without cSS", SP.CONFIRM_BALANCE)
        self.assertEqual(S["version"], "v002"); self.assertEqual(S["mode"], "balanced")
        for p in [f"TC{i}" for i in range(5)] + [f"TN{i}" for i in range(4)] + list(P["add"]): self.assertEqual(S["assignment"][p], "test")
        self.assertTrue(os.path.exists(os.path.join(st, "split", "v001.json")))          # the previous version is kept
        self.assertEqual(SP.partition_of(st, list(P["add"])[0]), "test")
        with self.assertRaises(SP.SplitError): SP.balance(st, cl, "Dr A", "again", SP.CONFIRM_BALANCE)   # nothing left to balance

    def test_never_trained_unreviewed_or_below_the_development_floor(self):
        st, cl = store_with(2, 5, 9, 20)
        frozen = {f"DC{i}" for i in range(9)}
        P = SP.balance_plan(st, cl, frozen=frozen); self.assertEqual(P["add"], {}); self.assertIn("already used to train", P["short"]["css"])
        P = SP.balance_plan(st, cl)                                                   # 9 development cSS patients: only 1 may move (floor 8)
        self.assertEqual(sum(1 for k in P["add"].values() if k == "css"), 1); self.assertIn("css", P["short"])
        cl2 = {k: v for k, v in cl.items() if k != "DN0"}                             # no finished review: never moved
        self.assertNotIn("DN0", SP.balance_plan(st, cl2)["add"])


class TestMarksCountAsCss(unittest.TestCase):
    def test_patient_classes_include_marked_patients(self):
        rows, _ = rows_and_marks()
        test = [r for r in rows if r["test"]]; tp = sorted({r["patient"] for r in test})
        neg_only = [p for p in tp if not any(r["y"] == 1 for r in test if r["patient"] == p)]
        m0 = MT.train_cycle(rows, "v970", cnn_epochs=0, nested=False)
        m1 = MT.train_cycle(rows, "v971", cnn_epochs=0, nested=False, test_css_patients=set(neg_only[:1]) | {"not_a_test_patient"})
        a, b = m0["test"]["patient_classes"], m1["test"]["patient_classes"]
        if neg_only:
            self.assertEqual(b["with_css"], a["with_css"] + 1); self.assertEqual(b["without_css"], a["without_css"] - 1)
            self.assertEqual(b["from_missed_marks"], 1)
        self.assertEqual(a["with_css"] + a["without_css"], b["with_css"] + b["without_css"])


if __name__ == "__main__":
    unittest.main()
