"""Stage 2 P2: css-patch/2.0 - 1.0 surface patch bit-identical to the production extractor, native 2.5D stack without through-plane
interpolation, storage-order invariance, channel refusals, provenance, synthetic-only (synthetic data)."""
import csv, glob, json, os, shutil, subprocess, sys, tempfile, unittest
import numpy as np
import nibabel as nib
import _common  # noqa: F401
from uengine import provenance as pv
from uengine.imaging import NotSynthetic, patches as PT, synthetic_images as S

KEYS_10 = None


def truth(base, sid):
    with open(os.path.join(base, "unified_engine", "image_truth", f"{sid}.csv")) as f:
        return {(r["list"], int(r["id"])): r["kind"] for r in csv.DictReader(f)}


def tree(base):
    return {os.path.relpath(os.path.join(r, f), base): os.path.getmtime(os.path.join(r, f)) for r, _, fs in os.walk(base) for f in fs}


class Base(unittest.TestCase):
    def setUp(self): self.B = tempfile.mkdtemp(prefix="uengine_img_p2_")
    def tearDown(self): shutil.rmtree(self.B, ignore_errors=True)


class TestFidelity(Base):
    def test_surface_patch_bit_identical_to_production_cli(self):
        S.write_study(self.B, "SYN01"); PT.extract_study(self.B, "SYN01", write=True)
        r = subprocess.run([sys.executable, PT.SAP_FILE, "SYN01"], env=dict(os.environ, CSS_BASE=self.B), capture_output=True, text=True,
                           timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        files = sorted(glob.glob(os.path.join(self.B, "review", "SYN01_patches", "*.npz"))); self.assertEqual(len(files), 6)
        n = 0
        for p in files:
            with np.load(p) as a, np.load(os.path.join(self.B, "unified_engine", "patches", "SYN01", os.path.basename(p))) as b:
                m10 = json.loads(str(a["metadata_json"])); m20 = json.loads(str(b["metadata_json"]))
                for k in a.files:
                    if k == "metadata_json": continue
                    self.assertEqual((a[k].dtype, a[k].shape), (b[k].dtype, b[k].shape), k)
                    self.assertEqual(a[k].tobytes(), b[k].tobytes(), f"{p} {k}"); n += 1
                for k in ("size_mm", "spacing_mm", "axis_semantics", "normal_sign", "normal_flipped", "channels", "cand_uid", "obj_id", "list"):
                    self.assertEqual(m10[k], m20[k], k)
        self.assertEqual(n, 90)

    def test_pinned_extractor_required(self):
        S.write_study(self.B, "SYN01"); old = PT.SAP_SHA256
        try:
            PT.SAP_SHA256 = "0" * 64
            with self.assertRaises(pv.ProvenanceError): PT.extract_study(self.B, "SYN01")
        finally: PT.SAP_SHA256 = old


class TestContent(Base):
    @classmethod
    def setUpClass(cls):
        cls.B0 = tempfile.mkdtemp(prefix="uengine_img_p2c_"); S.write_study(cls.B0, "SYN01")
        cls.r = PT.extract_study(cls.B0, "SYN01"); cls.T = truth(cls.B0, "SYN01")

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.B0, ignore_errors=True)

    def test_rows_and_skip(self):
        st = {(x["list"], x["obj_id"]): (x["status"], x["skip_reason"]) for x in self.r["rows"]}
        self.assertEqual(st[("excluded", 2)], ("skipped", "object has 2 voxels (< 3)"))
        self.assertEqual(sum(v[0] == "ok" for v in st.values()), 6)
        for x in self.r["rows"]:
            self.assertEqual(x["object_key"], pv.sha256_text(x["cand_uid"] + "|SYNTHETIC-P2"))

    def test_frame_separates_subpial_sheet_from_surface_tube(self):
        for (lst, oid), kind in self.T.items():
            row = next((x for x in self.r["rows"] if x["list"] == lst and x["obj_id"] == oid), None)
            if kind == "css_band": self.assertLess(row["pial_sd_at_center_mm"], 0, (lst, oid))        # below the pial surface
            if kind == "surface_vein": self.assertGreater(row["pial_sd_at_center_mm"], 0, (lst, oid))  # in the CSF
        ext = {"css_band": [], "surface_vein": [], "transcortical_vein": []}
        for (lst, oid), P in self.r["patches"].items():
            om = P["object_mask"]; self.assertTrue(om.any(), (lst, oid))
            nz = np.argwhere(om); n_extent = (nz[:, 2].max() - nz[:, 2].min() + 1) * 0.5; v_extent = (nz[:, 1].max() - nz[:, 1].min() + 1) * 0.5
            if self.T[(lst, oid)] == "transcortical_vein": self.assertGreater(n_extent, v_extent)              # crosses the cortex along n
            ext[self.T[(lst, oid)]].append(v_extent)
            if self.T[(lst, oid)] == "css_band": self.assertGreater(v_extent, 2 * n_extent)                     # a sheet: wide across, thin along n
        self.assertGreater(min(ext["css_band"]), 2 * max(ext["surface_vein"]))                                   # sheet vs tube across the surface

    def test_native_stack_axes_and_validity(self):
        for P in self.r["patches"].values():
            self.assertEqual(P["native_swi"].shape, (5, 65, 65)); self.assertEqual(P["native_valid_swi"].shape, (5, 65, 65))
            self.assertGreater(P["native_ex_world"][0], 0.9); self.assertGreater(P["native_ey_world"][1], 0.9)
            z = P["native_slice_centres_mm"][:, 2]; self.assertTrue(np.all(np.diff(z) > 0))                     # inferior -> superior
            np.testing.assert_allclose(np.diff(z), 1.2, atol=1e-6)                                              # acquired slice spacing
            self.assertFalse(np.isnan(P["native_swi"][P["native_valid_swi"]]).any())
            self.assertTrue(P["native_object_mask"][2].any())                                                   # the object is on the centre slice

    def test_native_values_come_only_from_their_own_slice(self):
        P = self.r["patches"][("candidates", 1)]
        swi = nib.load(os.path.join(self.B0, "data", "SYN01_swi.nii")); D = np.asarray(swi.dataobj, np.float32)
        from scipy import ndimage as ndi
        A = swi.affine; Ainv = np.linalg.inv(A)
        ax = (np.arange(65) - 32) * 0.5; a, b = np.meshgrid(ax, ax, indexing="ij")
        for s, k in enumerate(P["native_slice_k"]):
            cw = P["native_slice_centres_mm"][s]
            Wp = cw + a[..., None] * P["native_ex_world"] + b[..., None] * P["native_ey_world"]
            V = (Ainv[:3, :3] @ Wp.reshape(-1, 3).T).T + Ainv[:3, 3]
            self.assertLess(float(np.abs(V[:, 2] - k).max()), 1e-6)                                            # on the acquired plane
            two_d = ndi.map_coordinates(D[:, :, int(k)], V[:, :2].T, order=1, mode="constant", cval=np.nan, prefilter=False).reshape(65, 65)
            ok = P["native_valid_swi"][s]
            np.testing.assert_allclose(P["native_swi"][s][ok], two_d[ok], atol=1e-6)

    def test_native_slices_outside_the_array_are_invalid(self):
        swi = nib.load(os.path.join(self.B0, "data", "SYN01_swi.nii")); D = np.asarray(swi.dataobj)
        obj = np.array([[40, 40, 0], [41, 40, 0], [42, 40, 1]])
        ns = PT.native_stack({"swi": swi}, swi.affine, obj, D > 0)
        valid_slices = ns["valids"]["native_valid_swi"].any(axis=(1, 2))
        self.assertEqual(valid_slices.tolist()[:2], [False, False])
        self.assertTrue(np.isnan(ns["arrays"]["native_swi"][0]).all())


class TestInvariance(Base):
    def test_storage_order_gives_the_same_patches(self):
        out = {}
        for code in ("RAS", "LPS", "RPI"):
            b = os.path.join(self.B, code); S.write_study(b, "SYN01", axcodes=code, noise=0.0)
            out[code] = PT.extract_study(b, "SYN01")["patches"]
        for code in ("LPS", "RPI"):
            self.assertEqual(sorted(out[code]), sorted(out["RAS"]))
            for key, P in out["RAS"].items():
                Q = out[code][key]
                for k in ("u_world", "v_world", "n_world", "center_world_mm", "native_ex_world", "native_ey_world", "native_slice_centres_mm"):
                    np.testing.assert_allclose(Q[k], P[k], atol=1e-4, err_msg=f"{code} {key} {k}")
                for k in ("image_swi", "image_flair", "native_swi", "native_flair"):
                    ok = P[k.replace("image_", "valid_").replace("native_", "native_valid_")]
                    np.testing.assert_allclose(Q[k][ok], P[k][ok], atol=1e-4, err_msg=f"{code} {key} {k}")
                np.testing.assert_array_equal(Q["native_object_mask"], P["native_object_mask"])


class TestRefusalAndProvenance(Base):
    def test_unusable_channel_is_absent_everywhere(self):
        S.write_study(self.B, "SYN01", flair_shift_mm=(0, 0, 2.6)); r = PT.extract_study(self.B, "SYN01")
        for P in r["patches"].values():
            self.assertNotIn("image_flair", P); self.assertNotIn("native_flair", P)
            self.assertFalse(P["valid_flair"].any()); self.assertFalse(P["native_valid_flair"].any())
            m = json.loads(P["metadata_json"]); self.assertEqual(m["missing_channels"], {"flair": "misregistered"})
            self.assertNotIn("flair", m["channels"])

    def test_refused_geometry_and_missing_frame_block_every_object(self):
        S.write_study(self.B, "SYN01", axcodes="SAR"); r = PT.extract_study(self.B, "SYN01", write=True)
        self.assertTrue(r["blocked"].startswith("study geometry: geometry_refused")); self.assertEqual(r["patches"], {})
        self.assertTrue(all(x["status"] == "skipped" and x["skip_reason"] == r["blocked"] for x in r["rows"]))
        self.assertEqual(sorted(os.listdir(os.path.join(self.B, "unified_engine", "patches", "SYN01"))), ["manifest.csv"])
        b2 = os.path.join(self.B, "nopial"); S.write_study(b2, "SYN02", channels=("swi", "flair", "labels"))
        r = PT.extract_study(b2, "SYN02"); self.assertIn("no surface frame", r["blocked"])

    def test_non_synthetic_refused(self):
        os.makedirs(os.path.join(self.B, "review")); before = tree(self.B)
        with self.assertRaises(NotSynthetic): PT.extract_study(self.B, "SYN01", write=True)
        S.write_study(self.B + "_s", "SYN01")
        with self.assertRaises(NotSynthetic): PT.extract_study(self.B + "_s", "M01", write=True)
        shutil.rmtree(self.B + "_s"); self.assertEqual(tree(self.B), before)

    def test_writes_only_its_folder_and_is_reproducible(self):
        S.write_study(self.B, "SYN01"); before = tree(self.B)
        r1 = PT.extract_study(self.B, "SYN01", write=True); after = tree(self.B)
        new = {k for k in after if k not in before}
        self.assertTrue(new and all(k.startswith("unified_engine/patches/SYN01/") for k in new), new)
        self.assertEqual({k: v for k, v in after.items() if k in before}, before)
        r2 = PT.extract_study(self.B, "SYN01")
        sha = lambda r: [x["patch_sha"] for x in r["rows"] if x["status"] == "ok"]
        self.assertEqual(len(sha(r1)), 6); self.assertEqual(sha(r1), sha(r2))
        p = os.path.join(self.B, r1["rows"][0]["patch_path"]); arrs, meta = PT.load_patch(p)
        self.assertEqual(meta["schema"], "css-patch/2.0"); self.assertTrue(meta["synthetic"])
        self.assertEqual(set(meta["image_sha256"]), {"swi", "phase", "flair", "labels"})
        self.assertFalse(meta["native"]["through_plane_interpolation"])
        arrs["image_swi"][0, 0, 0] += 1.0; arrs["metadata_json"] = json.dumps(meta)
        np.savez_compressed(p, **arrs)
        with self.assertRaises(ValueError): PT.load_patch(p)
        with open(os.path.join(self.B, "unified_engine", "patches", "SYN01", "manifest.csv")) as f: rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 7); self.assertNotIn("kind", rows[0])                                   # no truth in the manifest


if __name__ == "__main__":
    unittest.main()
