"""Stage 2 P1: registration provenance (LTA, reg.json) and image-based residual-shift check (synthetic)."""
import json, os, shutil, tempfile, unittest
import numpy as np
import _common  # noqa: F401
from uengine.imaging import geometry as G, registration as RG, synthetic_images as S


class Base(unittest.TestCase):
    def setUp(self):
        self.B = tempfile.mkdtemp(prefix="uengine_img_reg_"); self.paths = S.write_study(self.B, "SYN01")
        self.swi = self.paths["swi"]; self.d = G.describe(S.nib.load(self.swi))

    def tearDown(self): shutil.rmtree(self.B, ignore_errors=True)


class TestLTA(Base):
    def test_type0_and_type1_give_the_same_ras2ras(self):
        M = S.rigid((2.0, -1.0, 3.0), (4.0, -2.0, 1.5)); t1A, t1s = S.grid_affine((1, 1, 1))
        swi = S.nib.load(self.swi); src = (swi.affine, swi.shape, "data/SYN01_swi.nii"); dst = (t1A, t1s, "orig.mgz")
        p0, p1 = os.path.join(self.B, "a.lta"), os.path.join(self.B, "b.lta")
        S.write_lta(p0, M, src, dst, lta_type=0); S.write_lta(p1, M, src, dst, lta_type=1)
        r0 = RG.lta_record(p0, self.B, self.d, self.swi, "src"); r1 = RG.lta_record(p1, self.B, self.d, self.swi, "src")
        self.assertEqual((r0["type"], r1["type"]), (0, 1))
        np.testing.assert_allclose(r0["ras2ras"], M, atol=1e-5); np.testing.assert_allclose(r1["ras2ras"], M, atol=1e-6)
        self.assertEqual((r0["status"], r1["status"]), ("ok", "ok")); self.assertEqual(r0["volinfo_check"], "matches the SWI")
        self.assertAlmostEqual(r0["translation_mm"], float(np.linalg.norm([4.0, -2.0, 1.5])), places=3)

    def test_rigid_params(self):
        r = RG.rigid_params(S.rigid((0, 0, 5.0), (1, 2, 3)))
        self.assertAlmostEqual(r["rotation_deg"], 5.0, places=3); self.assertLess(r["scale_dev"], 1e-9)
        self.assertAlmostEqual(r["translation_mm"], float(np.sqrt(14)), places=4)

    def test_non_rigid_refused(self):
        M = S.rigid(); M[:3, :3] *= 1.1; p = os.path.join(self.B, "s.lta"); S.write_lta(p, M)
        r = RG.lta_record(p, self.B, self.d, self.swi, "src"); self.assertEqual(r["status"], "invalid"); self.assertIn("rigid", r["reasons"][0])

    def test_lta_made_for_another_image_refused(self):
        other_A, other_s = S.grid_affine((0.7, 0.7, 1.5)); p = os.path.join(self.B, "o.lta")
        S.write_lta(p, S.rigid(), src=(other_A, other_s, "x.nii"), dst=(other_A, other_s, "y.nii"), lta_type=0)
        r = RG.lta_record(p, self.B, self.d, self.swi, "src")
        self.assertEqual(r["status"], "invalid"); self.assertEqual(r["volinfo_check"], "MISMATCH")

    def test_missing_stale_garbage(self):
        self.assertEqual(RG.lta_record(os.path.join(self.B, "none.lta"), self.B, self.d, self.swi, "src")["status"], "missing")
        p = self.paths["swi2t1"]; S.make_older(p, self.swi)
        self.assertEqual(RG.lta_record(p, self.B, self.d, self.swi, "src")["status"], "stale")
        g = os.path.join(self.B, "g.lta")
        with open(g, "w") as f: f.write("not an lta\n")
        r = RG.lta_record(g, self.B, self.d, self.swi, "src"); self.assertEqual(r["status"], "invalid"); self.assertIn("unreadable", r["reasons"][0])

    def test_reg_json_cost_threshold_is_css_qc(self):
        self.assertEqual(RG.REG_COST_LOW_CONF, 0.8)
        p = os.path.join(self.B, "work", "SYN01_reg.json")
        self.assertFalse(RG.reg_json(p, self.B)["cost_above_threshold"])
        with open(p, "w") as f: json.dump(dict(method="bbregister", cost=0.93), f)
        r = RG.reg_json(p, self.B); self.assertTrue(r["cost_above_threshold"]); self.assertEqual(r["method"], "bbregister")
        with open(p, "w") as f: json.dump(dict(method="mri_coreg", cost=None), f)
        self.assertFalse(RG.reg_json(p, self.B)["cost_above_threshold"])


class TestResidualShift(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.A, cls.shape = S.grid_affine((0.8, 0.8, 1.2)); cls.swi = S.sample("swi", cls.A, cls.shape, noise=0.01, seed=1)

    def shift(self, s, noise=0.01, inverted=False):
        fl = S.sample("flair", self.A, self.shape, noise=noise, seed=2, shift_mm=s)
        if inverted: fl = fl.max() - fl
        return RG.residual_shift(self.swi, fl, (0.8, 0.8, 1.2), self.A)

    def test_shift_recovered_and_classified(self):
        for s, want in (((0, 0, 0), "ok"), ((0.6, 0, 0), "ok"), ((0, 1.5, 0), "low_confidence"), ((0, 0, 2.4), "misregistered"),
                        ((2.0, 2.0, 0), "misregistered")):
            r = self.shift(s); self.assertEqual(r["status"], want, (s, r))
            np.testing.assert_allclose(r["shift_world_mm"], s, atol=0.35, err_msg=str(s))

    def test_contrast_agnostic(self):
        r = self.shift((0, 0, 2.4), inverted=True); self.assertEqual(r["status"], "misregistered")
        np.testing.assert_allclose(r["shift_world_mm"], (0, 0, 2.4), atol=0.35)

    def test_beyond_search_is_misregistered(self):
        r = self.shift((6.0, 0, 0)); self.assertEqual(r["status"], "misregistered")

    def test_noise_only_channel_unmeasurable(self):
        noise = np.random.default_rng(5).normal(0, 1, self.shape)
        self.assertEqual(RG.residual_shift(self.swi, noise, (0.8, 0.8, 1.2), self.A)["status"], "unmeasurable")


if __name__ == "__main__":
    unittest.main()
