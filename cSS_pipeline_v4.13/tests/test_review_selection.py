"""2026-11-25 Review menu: "Review all not yet reviewed" (every cohort) and "Choose cohorts..." (one or several, only not yet reviewed by
default) open the reviewer on exactly those studies; reviewed, archived, retired and unprocessed studies are left out. Temporary project.
Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)


class TestReviewSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import css_app
        cls.A = css_app

    def test_selection_and_counts(self):
        A = self.A; B = A.B; os.makedirs(os.path.join(B, "review"), exist_ok=True)
        pats = [dict(code="RS-10", cohort="c1", status="done"), dict(code="RS-2", cohort="c1", status="done"),
                dict(code="RS-3", cohort="c2", status="done"), dict(code="RS-4", cohort="", status="done"),
                dict(code="RS-5", cohort="c2", status="done", archived={"at": "x"}), dict(code="RS-6", cohort="c2", status="waiting"),
                dict(code="RS-7", cohort="c2", status="done")]
        for p in pats:
            if p["code"] != "RS-7": open(os.path.join(B, "review", f"{p['code']}_candidates.csv"), "w").write("cand_id\n1\n")
        reviewed = {"RS-2"}
        with mock.patch.object(A, "PAT", pats), mock.patch.object(A, "review_open", side_effect=lambda c, coh="": c not in reviewed):
            self.assertEqual(A.review_selection(None, True), ["RS-3", "RS-4", "RS-10"])        # every cohort, natural order, reviewed left out
            self.assertEqual(A.review_selection(["c1"], True), ["RS-10"])
            self.assertEqual(A.review_selection(["c1", "c2"], True), ["RS-3", "RS-10"])        # several cohorts
            self.assertEqual(A.review_selection(["c1"], False), ["RS-2", "RS-10"])             # reviewed included when asked
            self.assertEqual(A.review_selection(["-"], True), ["RS-4"])                        # studies without a cohort
            self.assertEqual(A.review_counts(), [dict(cohort="-", total=1, open=1), dict(cohort="c1", total=2, open=1), dict(cohort="c2", total=1, open=1)])

    def test_menu_is_wired(self):
        src = open(os.path.join(ROOT, "app", "css_app.html")).read()
        for k in ('id="srev1"', 'id="srev2"', 'id="srev3"', "function reviewCohortsDlg(", 'id="rcOpen" checked', 'id="rvopen"', "only_open:true"):
            self.assertIn(k, src)


if __name__ == "__main__":
    unittest.main()
