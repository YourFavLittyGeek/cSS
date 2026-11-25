"""2026-11-25 reviewer speed: candidate centres from bounding boxes are identical to the old whole-volume computation;
the next study of the cohort is the one preloaded."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import sys
import unittest

import numpy as np
from scipy import ndimage as ndi

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.argv = ["test"]
import review_web as RW                                                       # noqa: E402


def old_centres(lab, ids, shape):
    out = {}
    com = ndi.center_of_mass(lab > 0, lab, ids)
    for i, c in zip(ids, com):
        c = np.round(c).astype(int) if np.all(np.isfinite(c)) else np.array(shape) // 2
        if lab[tuple(c)] != i:
            pts = np.argwhere(lab == i)
            if len(pts): c = pts[np.argmin(((pts - c) ** 2).sum(1))]
        out[i] = [int(v) for v in c]
    return out


class TestCentres(unittest.TestCase):
    def test_identical_to_the_old_computation(self):
        rng = np.random.default_rng(3)
        lab = np.zeros((60, 50, 30), np.uint16)
        lab[5:9, 5:9, 5:8] = 1                                          # compact
        yy, xx = np.mgrid[0:40, 0:40]                                   # ring (curved: centre not its own voxel)
        ring = (np.abs(np.hypot(yy - 20, xx - 20) - 12) < 1.5)
        lab[10:50, 5:45, 15][ring] = 7
        lab[50:52, 40:49, 2:28] = 4101                                  # long thin, large id
        for k in range(20):                                             # random specks
            i, j, z = rng.integers(0, 55), rng.integers(0, 45), rng.integers(0, 28)
            lab[i:i + 2, j:j + 2, z:z + 2] = 200 + k
        ids = [1, 7, 4101, 9999] + [200 + k for k in range(20)]            # 9999 absent -> middle of the volume
        ids = [i for i in ids if i == 9999 or (lab == i).any()]
        self.assertEqual(RW.candidate_centres(lab, ids, lab.shape), old_centres(lab, ids, lab.shape))
        self.assertEqual(RW.candidate_centres(lab, [], lab.shape), {})


class TestPreloadOrder(unittest.TestCase):
    def test_next_in_the_cohort_then_in_the_list(self):
        RW.IDS[:] = ["A1", "A2", "B1", "A3"]
        RW.GROUPS.clear(); RW.GROUPS.update({"A": ["A1", "A2", "A3"], "B": ["B1"]})
        self.assertEqual(RW._next_of("A2"), "A3")
        self.assertIsNone(RW._next_of("A3"))
        self.assertIsNone(RW._next_of("B1"))
        RW.GROUPS.clear()
        self.assertEqual(RW._next_of("A2"), "B1")


if __name__ == "__main__":
    unittest.main()
