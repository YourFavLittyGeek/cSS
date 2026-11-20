"""Stage 2 P1: geometry description and gate - verbatim production rules, reorientation invariance, every refusal path (synthetic)."""
import unittest
import numpy as np
import _common  # noqa: F401  (CSS_BASE -> temporary folder)
from scipy.spatial.transform import Rotation
from uengine.imaging import geometry as G, synthetic_images as S, verify_sources


def _img(vox=(0.8, 0.8, 1.2), rot=(0, 0, 0), axcodes="RAS", qcode=1, scode=1, channel="swi"):
    A, shape = S.grid_affine(vox, rot_deg=rot)
    return S.reorient(S.nifti(S.sample(channel, A, shape), A, qcode, scode), axcodes)


class TestProduction(unittest.TestCase):
    def test_pinned_sources(self):
        self.assertEqual(verify_sources(), [])

    def test_orientation_block_is_css_qc_and_matches_replica_and_detector(self):
        self.assertIn('qc["obliquity_deg"]', G._QC_ORIENT_SRC); self.assertIn('qc["orientation_ok"]', G._QC_ORIENT_SRC)
        rng = np.random.default_rng(3)
        for _ in range(300):
            vox = rng.uniform(0.4, 3.0, 3); R = Rotation.random(random_state=rng).as_matrix() if rng.random() < 0.5 else \
                Rotation.from_euler("xyz", rng.uniform(-30, 30, 3), degrees=True).as_matrix()
            A = np.eye(4); A[:3, :3] = R @ np.diag(vox)
            got = G.qc_orientation(A, vox)
            si = int(np.argmax(np.abs(A[2, :3]))); n = A[:3, si] / np.linalg.norm(A[:3, si])
            self.assertEqual(got["si_axis"], si)
            self.assertEqual(got["obliquity_deg"], round(float(np.degrees(np.arccos(min(1.0, abs(n[2]))))), 1))
            ok = bool(si == 2 and vox[2] >= max(vox[0], vox[1]) - 1e-3)
            self.assertEqual(got["orientation_ok"], ok)
            self.assertEqual(G.detector_would_stop(A, vox), not ok)       # the detector's own condition agrees with css_qc


class TestInvariance(unittest.TestCase):
    def test_storage_order_does_not_change_world_samples(self):
        ref = _img(); pts = np.random.default_rng(0).uniform(-30, 30, (400, 3)) * [1, 1.1, 0.8]
        v0 = G.sample_world(np.asanyarray(ref.dataobj), ref.affine, pts); d0 = G.describe(ref)
        self.assertTrue(np.isfinite(v0).all())
        for code in ("LAS", "LPS", "RPI", "LPI", "PRS", "ALS"):
            im = S.reorient(ref, code); d = G.describe(im)
            self.assertEqual(d["axcodes"], code)
            v = G.sample_world(np.asanyarray(im.dataobj), im.affine, pts)
            self.assertLess(float(np.abs(v - v0).max()), 1e-4, code)
            np.testing.assert_allclose(d["world_min_mm"], d0["world_min_mm"], atol=1e-4)
            np.testing.assert_allclose(d["world_max_mm"], d0["world_max_mm"], atol=1e-4)
            self.assertEqual(sorted(d["zooms_mm"]), sorted(d0["zooms_mm"]))
            self.assertEqual(G.gate(d)["status"], "ok", code)

    def test_oblique_grid_samples_the_same_world_object(self):
        ob = _img(rot=(12, -6, 4)); pts = np.random.default_rng(1).uniform(-20, 20, (300, 3))
        v = G.sample_world(np.asanyarray(ob.dataobj), ob.affine, pts); truth = S.phantom(pts, "swi")
        far = np.abs(S.signed_distance(pts)) > 2.0                        # away from edges, interpolation error is small
        self.assertLess(float(np.nanmedian(np.abs(v - truth)[far])), 0.02)


class TestGate(unittest.TestCase):
    def st(self, im): return G.gate(G.describe(im))

    def test_clean(self):
        g = self.st(_img()); self.assertEqual(g["status"], "ok"); self.assertEqual(g["reasons"], [])

    def test_slice_axis_not_si_refused(self):
        for code in ("ASR", "SAR", "RSA", "LIP"):
            g = self.st(S.reorient(_img(), code))
            self.assertEqual(g["status"], "geometry_refused", code)
            self.assertEqual([f["check"] for f in g["findings"]], ["slice_axis"], code)   # no misleading voxel-size finding

    def test_isotropic_any_si_axis_2_is_ok(self):
        self.assertEqual(self.st(_img(vox=(0.9, 0.9, 0.9)))["status"], "ok")

    def test_obliquity(self):
        g = self.st(_img(rot=(10, 0, 0))); self.assertEqual(g["status"], "ok")
        self.assertAlmostEqual(G.describe(_img(rot=(10, 0, 0)))["obliquity_deg"], 10.0, places=1)
        g = self.st(_img(rot=(28, 0, 0))); self.assertEqual(g["status"], "low_confidence"); self.assertIn("obliquity", g["findings"][0]["check"])

    def test_voxel_envelope(self):
        self.assertEqual(self.st(_img(vox=(0.8, 0.8, 2.2)))["status"], "low_confidence")       # css_qc thick slices
        g = self.st(_img(vox=(0.8, 0.8, 3.0))); self.assertEqual(g["status"], "quality_refused")
        g = self.st(_img(vox=(1.2, 1.2, 1.5))); self.assertEqual(g["status"], "quality_refused")

    def test_header_codes_zero_refused(self):
        g = self.st(_img(qcode=0, scode=0)); self.assertEqual(g["status"], "geometry_refused")
        self.assertTrue(any(f["check"] == "header_codes" for f in g["findings"]))
        self.assertEqual(self.st(_img(qcode=0, scode=1))["status"], "ok")

    def test_bad_affines(self):
        im = _img(); d = G.describe(im)
        for bad in ("nan", "singular"):
            dd = dict(d); A = np.array(d["affine"])
            if bad == "nan": A[0, 3] = np.nan; dd.update(affine_finite=False, det=None)
            else: A[:3, 2] = 0; dd.update(det=0.0)
            dd["affine"] = A.tolist()
            self.assertEqual(G.gate(dd)["status"], "geometry_refused", bad)

    def test_zooms_disagree_with_affine_refused(self):
        im = _img(); im.header.set_zooms((0.8, 0.8, 2.0))
        g = self.st(im); self.assertEqual(g["status"], "geometry_refused")
        self.assertTrue(any(f["check"] == "zooms_vs_affine" for f in g["findings"]))

    def test_qform_sform_disagree_refused(self):
        im = _img(); A = im.affine.copy(); B = A.copy(); B[0, 3] += 2.0
        im.set_qform(A, code=1); im.set_sform(B, code=1)
        g = self.st(im); self.assertTrue(any(f["check"] == "qform_vs_sform" for f in g["findings"]))
        self.assertEqual(g["status"], "geometry_refused")

    def test_4d_refused(self):
        A, shape = S.grid_affine((0.8, 0.8, 1.2), fov_mm=(20, 20, 20))
        im = S.nifti(np.zeros(shape + (3,), np.float32), A)
        self.assertTrue(any(f["check"] == "dimensions" for f in self.st(im)["findings"]))

    def test_same_grid(self):
        a = G.describe(_img()); b = dict(a); B = np.array(a["affine"]); B[0, 3] += 5e-5; b["affine"] = B.tolist()
        self.assertTrue(G.same_grid(a, b)); B[0, 3] += 1e-3; b["affine"] = B.tolist(); self.assertFalse(G.same_grid(a, b))
        self.assertFalse(G.same_grid(a, G.describe(S.reorient(_img(), "LAS"))))          # same object, other storage: not the same grid


if __name__ == "__main__":
    unittest.main()
