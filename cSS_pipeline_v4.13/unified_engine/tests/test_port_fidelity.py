"""the repository engine reproduces the isolated, tested workspace prototype (~/cSS_ml_work) exactly on the same SYNTHETIC cohort.
Skipped (reported as skipped, never as passed) where the workspace is not present."""
import importlib, os, sys, unittest
import numpy as np
import _common  # noqa: F401
from uengine import synthetic as sy, experiment as ex
from uengine.prototype.fusion import UnifiedScorer

WS = os.path.expanduser("~/cSS_ml_work/src")


@unittest.skipUnless(os.path.isdir(os.path.join(WS, "cssml")), "workspace ~/cSS_ml_work not present")
class TestPortFidelity(unittest.TestCase):
    def test_identical_predictions_and_cohort(self):
        sys.path.insert(0, WS)
        try:
            wsy, wex, wfu = (importlib.import_module(m) for m in ("cssml.synthetic", "cssml.experiment", "cssml.prototype.fusion"))
        finally: sys.path.remove(WS)
        a, _, _ = sy.make_cohort(30, seed=77); b, _, _ = wsy.make_cohort(30, seed=77)
        import pandas.testing as pt; pt.assert_frame_equal(a, b)
        D = ex.population(a); W = wex.population(b)
        tr = D.patient_key.isin(sorted(D.patient_key.unique())[:22])
        p1 = [r.unified["p"] for r in UnifiedScorer("offset", n_boot=10, seed=3).fit(D[tr], D.y[tr].to_numpy()).predict(D[~tr])]
        p2 = [r.unified["p"] for r in wfu.UnifiedScorer("offset", n_boot=10, seed=3).fit(W[tr], W.y[tr].to_numpy()).predict(W[~tr])]
        np.testing.assert_allclose(p1, p2, rtol=0, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
