"""2026-11-25 LUMOS learns from the expert-marked missed cSS (user decision).
- the mark (rectangle / pen outline / point, reviewer canonical voxels) becomes an object on the SWI grid (dark voxels inside the drawn
  region) and gets an image patch from the SAME surface-aligned extractor as the candidates (a mark drawn on a candidate gives nearly
  the same LUMOS maps as that candidate);
- marks enter LUMOS training folds for training patients only: never a held-out fold patient, never a locked-test patient; every
  out-of-fold prediction and metric stays on candidates; the final model records how many marks it learned from;
- the app uses only eligible development marks that do not lie on a candidate the detector showed.
Synthetic data only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import nibabel as nib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "scripts"), os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)
from uengine.imaging import patches as PT, synthetic_images as SI   # noqa: E402
from uengine.percival import meta as MT                              # noqa: E402
from uengine.percival.cnn import IN_SHAPE, patch_maps                # noqa: E402


class TestMarkRegion(unittest.TestCase):
    def test_rect_pen_point(self):
        sh = (40, 40, 30)
        R = PT._mark_region(dict(shape="rect", plane="axial", strokes=[[[10, 10, 15], [14, 12, 15]]]), sh)
        self.assertEqual(sorted(set(np.argwhere(R)[:, 2])), [14, 15, 16])                  # +-1 slice through the axial plane
        self.assertEqual(R[:, :, 15].sum(), 5 * 3)
        sq = [[10, 10, 15], [20, 10, 15], [20, 20, 15], [10, 20, 15]]
        P = PT._mark_region(dict(shape="pen", plane="axial", strokes=[sq]), sh)
        self.assertTrue(P[15, 15, 15]); self.assertEqual(P[:, :, 15].sum(), 11 * 11)       # the outline is filled
        Pc = PT._mark_region(dict(shape="pen", plane="coronal", strokes=[[[10, 20, 5], [20, 20, 5], [20, 20, 15], [10, 20, 15]]]), sh)
        self.assertEqual(sorted(set(np.argwhere(Pc)[:, 1])), [19, 20, 21])
        Q = PT._mark_region(dict(shape="point", strokes=[[[5, 5, 5]]]), sh)
        self.assertEqual(Q.sum(), 27)
        with self.assertRaises(ValueError): PT._mark_region(dict(shape="rect", plane="axial", strokes=[[[0, 0, 0], [39, 39, 29]]]), sh)

    def test_object_is_the_dark_part(self):
        A = np.full((40, 40, 30), 100.0, np.float32); A[18:22, 20, 15] = 20.0; brain = np.ones(A.shape, bool)
        R = np.zeros(A.shape, bool); R[15:25, 15:25, 14:17] = True
        m, how = PT.mark_object(A, brain, R)
        self.assertEqual(int(m.sum()), 4); self.assertIn("dark", how)
        m2, how2 = PT.mark_object(np.full(A.shape, 100.0, np.float32), brain, R)       # nothing dark: the drawn region
        self.assertEqual(int(m2.sum()), int(R.sum())); self.assertIn("drawn region", how2)


class TestExtractor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = tempfile.mkdtemp(prefix="lumos_marks_"); SI.write_study(cls.B, "SYN01")
        cls.E = PT.extract_study(cls.B, "SYN01")

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.B, ignore_errors=True)

    def test_mark_around_a_candidate_gives_that_candidate_s_patch(self):
        swi = nib.load(os.path.join(self.B, "data", "SYN01_swi.nii")); lab = np.asarray(nib.load(os.path.join(self.B, "review", "SYN01_candidates.nii.gz")).dataobj)
        can = nib.as_closest_canonical(swi); n2c = np.linalg.inv(can.affine) @ swi.affine
        cand = {oid: patch_maps(a) for (lst, oid), a in self.E["patches"].items() if lst == "candidates"}
        marks, dice = {}, {}
        for oid in cand:
            v = np.argwhere(lab == oid); c = np.round((n2c[:3, :3] @ v.T).T + n2c[:3, 3]).astype(int)
            marks[f"missed_{oid}"] = dict(shape="rect", plane="", strokes=[[c.min(0).tolist(), c.max(0).tolist()]])   # drawn around the lesion
        r = PT.extract_marks(self.B, "SYN01", marks); self.assertIsNone(r["blocked"])
        self.assertEqual(set(r["patches"]), set(marks))
        for k, a in r["patches"].items():
            b = patch_maps(a); self.assertEqual(b.shape, IN_SHAPE); self.assertIn("dark voxels inside the mark", r["how"][k])
            own = int(k.split("_")[1]); cc = {o: np.corrcoef(b[1].ravel(), m[1].ravel())[0, 1] for o, m in cand.items()}
            self.assertEqual(max(cc, key=cc.get), own)                    # the patch shows the marked lesion, not another place

    def test_axial_mark_and_detector_dark_map(self):
        swi = nib.load(os.path.join(self.B, "data", "SYN01_swi.nii")); lab = np.asarray(nib.load(os.path.join(self.B, "review", "SYN01_candidates.nii.gz")).dataobj)
        can = nib.as_closest_canonical(swi); n2c = np.linalg.inv(can.affine) @ swi.affine
        oid = next(o for (lst, o) in self.E["patches"] if lst == "candidates")
        v = np.argwhere(lab == oid); c = np.round((n2c[:3, :3] @ v.T).T + n2c[:3, 3]).astype(int); k = int(np.median(c[:, 2])); on = c[c[:, 2] == k]
        mk = {"missed_1": dict(shape="rect", plane="axial", strokes=[[[int(on[:, 0].min() - 1), int(on[:, 1].min() - 1), k], [int(on[:, 0].max() + 1), int(on[:, 1].max() + 1), k]]])}
        r = PT.extract_marks(self.B, "SYN01", mk); self.assertIn("local brain", r["how"]["missed_1"])
        dp = os.path.join(self.B, "work", "SYN01_dark.nii.gz")
        nib.save(nib.Nifti1Image((lab == oid).astype(np.uint8), swi.affine), dp)      # the detector's dark map is preferred when present
        try:
            r2 = PT.extract_marks(self.B, "SYN01", mk); self.assertIn("detector dark map", r2["how"]["missed_1"])
            self.assertTrue(np.array_equal(r2["patches"]["missed_1"]["object_mask"].any(), True))
        finally: os.remove(dp)

    def test_bad_mark_is_skipped_not_fatal(self):
        r = PT.extract_marks(self.B, "SYN01", {"missed_9": dict(shape="point", strokes=[])})
        self.assertIn("missed_9", r["skipped"]); self.assertEqual(r["patches"], {})


def rows_and_marks(n_pat=24, seed=3):
    rng = np.random.default_rng(seed); rows, marks = [], []
    for q in range(n_pat):
        for c in range(6):
            y = int(rng.random() < 0.4); M = rng.normal(0, 1, IN_SHAPE).astype(np.float32); M[0, 6:9, 4:8] -= 1.5 * y
            rows.append(dict(study=f"S{q:02d}", cand_id=c + 1, patient=f"P{q:02d}", y=y, math=float(rng.normal(y)),
                             char={k: float(rng.normal(y * 0.5)) for k in MT.CHAR}, maps=M, test=q >= n_pat - 4))
        Mm = rng.normal(0, 1, IN_SHAPE).astype(np.float32); Mm[0, 6:9, 4:8] -= 1.5
        marks.append(dict(study=f"S{q:02d}", cand_id="missed_1", patient=f"P{q:02d}", y=1, maps=Mm, test=q >= n_pat - 4))
    return rows, marks


class TestTraining(unittest.TestCase):
    def test_marks_only_in_training_folds_and_compared(self):
        rows, marks = rows_and_marks(); dev = [r for r in rows if not r["test"]]
        seen = []; real = MT._fit_image
        def spy(kind, M, y, g, seed, epochs): seen.append((len(M), set(map(str, g)))); return real(kind, M, y, g, seed, epochs)
        F = MT.folds(np.array([r["patient"] for r in dev]), 5, 0)
        with mock.patch.object(MT, "_fit_image", side_effect=spy):
            Z, rep = MT.component_oof(dev, k=5, seed=0, cnn_epochs=0, image_kinds=["pixel_logistic"], char_kinds=["logistic"], image_extra=marks)
        self.assertEqual(len(Z["image"]), len(dev))                                        # predictions only for candidates
        self.assertEqual(len(seen), 2 * len(F))                                            # the same folds without, then with the marks
        for (n0, p0), (n1, p1), (tr, te) in zip(seen[:len(F)], seen[len(F):], F):
            held = {dev[j]["patient"] for j in te}
            self.assertEqual(n0, len(tr))
            self.assertFalse(p1 & held)                                                    # never a held-out patient's mark
            self.assertFalse(p1 & {m["patient"] for m in marks if m["test"]})              # never a locked-test patient
            self.assertEqual(n1, len(tr) + len({dev[j]["patient"] for j in tr}))           # candidates + one mark per training patient
        mk = rep["image"]["missed_marks"]
        self.assertEqual(mk["available"], 20); self.assertTrue(mk["used"]); self.assertLessEqual(mk["logloss_with"], mk["logloss_without"])

    def test_marks_that_hurt_are_not_used(self):
        rows, marks = rows_and_marks()
        bad = [dict(m, maps=-m["maps"]) for m in marks]                                    # the opposite picture labelled cSS
        dev = [r for r in rows if not r["test"]]
        Z, rep = MT.component_oof(dev, k=5, seed=0, cnn_epochs=0, image_kinds=["pixel_logistic"], char_kinds=["logistic"], image_extra=bad)
        mk = rep["image"]["missed_marks"]; self.assertFalse(mk["used"]); self.assertIn("not used", mk["decision"])
        m = MT.train_cycle(rows, "v902", cnn_epochs=0, nested=False, image_extra=bad)
        self.assertEqual(m["data"]["lumos_missed_marks"]["used"], 0); self.assertIn("not used", m["modules"]["LUMOS"]["loop"])

    def test_with_marks_filters_and_labels(self):
        rows, marks = rows_and_marks(6)
        M, y, g = np.zeros((2,) + IN_SHAPE, np.float32), np.array([0.0, 1.0]), np.array(["P00", "P01"])
        M2, y2, g2, n = MT._with_marks(M, y, g, marks, {"P00"})
        self.assertEqual((n, len(M2), list(y2), list(g2)), (1, 3, [0.0, 1.0, 1.0], ["P00", "P01", "P00"]))
        self.assertEqual(MT._with_marks(M, y, g, None, {"P00"})[3], 0)

    def test_train_cycle_records_and_excludes_test_marks(self):
        rows, marks = rows_and_marks()
        got = {}
        real = MT.component_oof
        def spy(dev, **k): got["extra"] = k.get("image_extra"); return real(dev, **k)
        with mock.patch.object(MT, "component_oof", side_effect=spy):
            m = MT.train_cycle(rows, "v900", cnn_epochs=0, nested=False, image_extra=marks)
        self.assertTrue(got["extra"]); self.assertFalse({x["patient"] for x in got["extra"]} & {r["patient"] for r in rows if r["test"]})
        L = m["data"]["lumos_missed_marks"]; self.assertEqual((L["available"], L["used"]), (24, 20))
        self.assertIn("learned from the expert-marked missed cSS", m["modules"]["LUMOS"]["loop"]); self.assertEqual(m["modules"]["LUMOS"]["missed_marks"], 20)
        m0 = MT.train_cycle(rows, "v901", cnn_epochs=0, nested=False)
        self.assertNotEqual(m0["data"]["dataset_hash"], m["data"]["dataset_hash"])           # the marks are part of the dataset identity
        self.assertEqual(m0["data"]["lumos_missed_marks"]["used"], 0)
        mn = MT.train_cycle(rows, "v903", cnn_epochs=0, nested=True, image_extra=marks)        # nested cross-fitting runs with the marks
        self.assertIn("nested", mn)


class TestAppSelection(unittest.TestCase):
    def test_only_eligible_development_marks_off_the_shown_candidates(self):
        import percival_gui as PG
        E = [dict(cand_id="missed_1", status="eligible", partition="development", y=1, detector_fate="not generated by the detector"),
             dict(cand_id="missed_2", status="eligible", partition="development", y=1, detector_fate="overlaps shown candidate #4"),
             dict(cand_id="missed_3", status="excluded", partition="development", y=None, detector_fate=""),
             dict(cand_id="missed_4", status="eligible", partition="test", y=1, detector_fate=""),
             dict(cand_id=7, status="eligible", partition="development", y=1)]
        G = [dict(cand_id=f"missed_{i}", test=False, patient="P1", maps=np.zeros(IN_SHAPE), y=1) for i in range(1, 5)]
        with mock.patch.object(PG, "gather_marks", return_value=G):
            self.assertEqual([m["cand_id"] for m in PG._lumos_marks("S1", E)], ["missed_1"])
        with mock.patch.object(PG, "gather_marks", side_effect=AssertionError("not called")):
            self.assertEqual(PG._lumos_marks("S1", E[2:4]), [])


if __name__ == "__main__":
    unittest.main()
