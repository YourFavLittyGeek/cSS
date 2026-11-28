"""2026-11-28 Milestone 3: ALBUS outline refinement (uengine/imaging/refine.py) and segmentation metrics (seg_metrics.py).
- the extent follows the dark lesion beyond the ridge core, stays inside the detector's dark map and 5 mm, never overlaps two candidates;
- it is stored as derived output with input hashes (stale -> remade), never as a label;
- metrics are exact on hand-made masks (Dice, IoU, surface distances in mm, boundary F1, lesion matching) and report 'no reference' rather
  than a number when no expert mask exists.
Synthetic volumes only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import sys
import tempfile
import unittest

import nibabel as nib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "unified_engine"), os.path.join(ROOT, "scripts")):
    if p not in sys.path: sys.path.insert(0, p)
from uengine.imaging import refine as RF          # noqa: E402
from uengine.imaging import seg_metrics as SM     # noqa: E402

SH = (40, 40, 20)


def scene():
    swi = np.full(SH, 100.0, np.float32)
    lesion = np.zeros(SH, bool); lesion[10:30, 18:23, 8:12] = True          # a band 5 voxels wide
    core = np.zeros(SH, np.int16); core[10:30, 20, 9:11] = 1                  # the detector's ridge core: its centre line only
    lesion2 = np.zeros(SH, bool); lesion2[10:30, 26:29, 8:12] = True; core[10:30, 27, 9:11] = 2   # a second candidate 3 voxels away
    far = np.zeros(SH, bool); far[2:6, 2:6, 2:6] = True                       # dark, but far from any core
    dark = lesion | lesion2 | far; swi[dark] = 20.0
    return swi, core, dark, lesion, lesion2, far


class TestRefine(unittest.TestCase):
    def test_extent(self):
        swi, core, dark, les, les2, far = scene()
        ext, M = RF.refine(core, dark, swi, (1.0, 1.0, 1.0))
        e1 = ext == 1
        self.assertTrue(np.array_equal(e1, les))                                   # the whole band, not the centre line
        self.assertFalse((ext[far] > 0).any())                                     # never beyond 5 mm / outside the dark map
        self.assertFalse((e1 & (ext == 2)).any()); self.assertTrue(np.array_equal(ext == 2, les2))
        self.assertGreater(M[1]["growth_ratio"], 4); self.assertEqual(M[1]["extent_slices"], 4); self.assertEqual(M[1]["core_slices"], 2)
        self.assertLess(M[1]["contrast_in_out"], 0.5); self.assertFalse(M[1]["leak_warning"])
        self.assertTrue(((ext > 0) <= (dark | (core > 0))).all())

    def test_leak_warning(self):
        swi = np.full(SH, 100.0, np.float32); core = np.zeros(SH, np.int16); core[20, 20, 10] = 1
        dark = np.ones(SH, bool)                                                  # everything dark: growth only stops at 5 mm
        _, M = RF.refine(core, dark, swi, (1.0, 1.0, 1.0)); self.assertTrue(M[1]["leak_warning"])

    def test_run_and_stale(self):
        b = tempfile.mkdtemp(prefix="m3_")
        for d in ("data", "review", "work"): os.makedirs(os.path.join(b, d))
        swi, core, dark, *_ = scene(); aff = np.diag([0.5, 0.5, 2.0, 1.0])
        nib.save(nib.Nifti1Image(swi, aff), os.path.join(b, "data", "S1_swi.nii"))
        nib.save(nib.Nifti1Image(core, aff), os.path.join(b, "review", "S1_candidates.nii.gz"))
        nib.save(nib.Nifti1Image(dark.astype(np.uint8), aff), os.path.join(b, "work", "S1_dark.nii.gz"))
        rec = RF.run(b, "S1"); self.assertEqual(rec["version"], RF.VERSION)
        self.assertTrue(os.path.exists(os.path.join(b, "review", "S1_extent.csv"))); self.assertIsNotNone(RF.current(b, "S1"))
        self.assertIn("never a label", rec["note"])
        core2 = core.copy(); core2[core2 == 2] = 0
        nib.save(nib.Nifti1Image(core2, aff), os.path.join(b, "review", "S1_candidates.nii.gz"))
        self.assertIsNone(RF.current(b, "S1"))                                     # candidates changed -> stale, never shown
        os.remove(os.path.join(b, "work", "S1_dark.nii.gz"))
        with self.assertRaises(FileNotFoundError): RF.run(b, "S1")

    def test_reviewer_wiring(self):
        src = open(os.path.join(ROOT, "scripts", "review_web.py")).read(); h = open(os.path.join(ROOT, "scripts", "review_web.html")).read()
        self.assertIn('q.get("kind") == "extent"', src); self.assertIn("RB.remap_labels(E_, ctx)", src)          # same blinded ids
        self.assertIn("&kind=extent", h); self.assertIn("if(!WSM)fetch(", h)                                       # never in whole-study search


class TestMetrics(unittest.TestCase):
    def test_overlap_exact(self):
        a = np.zeros((20, 20, 20), bool); a[5:15, 5:15, 5:15] = True
        b = np.zeros_like(a); b[5:15, 5:15, 6:16] = True                          # shifted by one slice
        o = SM.overlap(a, b, (1, 1, 1))
        self.assertAlmostEqual(o["dice"], 0.9); self.assertAlmostEqual(o["iou"], 900 / 1100); self.assertAlmostEqual(o["sensitivity"], 0.9)
        self.assertAlmostEqual(o["over_segmentation"], 0.1); self.assertEqual((o["ref_slices"], o["pred_slices"]), (10, 10))
        self.assertAlmostEqual(o["slice_recall"], 0.9); self.assertLessEqual(o["hd_max_mm"], 1.0 + 1e-9); self.assertGreater(o["boundary_f1"], 0.9)
        o2 = SM.overlap(a, b, (1, 1, 3)); self.assertAlmostEqual(o2["hd_max_mm"], 3.0)          # distances in mm (3 mm slices)

    def test_identical_and_lesions(self):
        a = np.zeros((20, 20, 20), bool); a[2:5, 2:5, 2:5] = True; a[12:16, 12:16, 12:16] = True
        p = np.zeros_like(a); p[12:16, 12:16, 12:16] = True; p[2:4, 15:18, 2:4] = True     # one hit, one miss, one false positive
        self.assertEqual(SM.overlap(a, a, (1, 1, 1))["dice"], 1.0)
        L = SM.lesion_match(a, p, (1, 1, 1))
        self.assertEqual((L["ref_lesions"], L["pred_lesions"], L["matched"]), (2, 2, 1)); self.assertAlmostEqual(L["lesion_f1"], 0.5)
        self.assertAlmostEqual(L["matched_dice_mean"], 1.0)

    def test_no_reference_no_number(self):
        r = SM.evaluate(None, np.ones((3, 3, 3), bool), (1, 1, 1)); self.assertFalse(r["available"]); self.assertNotIn("overall", r)


if __name__ == "__main__":
    unittest.main()
