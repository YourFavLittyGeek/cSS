"""Stage 2 P1: study index - synthetic-only refusal, channel states, provenance, determinism, nothing else written (synthetic)."""
import json, os, shutil, subprocess, sys, tempfile, unittest
import _common
from uengine.imaging import NotSynthetic, index as X, synthetic_images as S
from uengine.demo_base import MARKER


def tree(base):
    out = {}
    for r, _, fs in os.walk(base):
        for f in fs:
            p = os.path.join(r, f); out[os.path.relpath(p, base)] = (os.path.getsize(p), os.path.getmtime(p))
    return out


class Base(unittest.TestCase):
    def setUp(self): self.B = tempfile.mkdtemp(prefix="uengine_img_idx_")
    def tearDown(self): shutil.rmtree(self.B, ignore_errors=True)


class TestRefusal(Base):
    def test_non_synthetic_base_refused_before_reading(self):
        os.makedirs(os.path.join(self.B, "data"))
        with open(os.path.join(self.B, "data", "SYN01_swi.nii"), "w") as f: f.write("x")
        before = tree(self.B)
        with self.assertRaises(NotSynthetic): X.index_study(self.B, "SYN01", write=True)
        self.assertEqual(tree(self.B), before)

    def test_non_syn_study_code_refused_on_synthetic_base(self):
        S.write_study(self.B, "SYN01"); before = tree(self.B)
        for sid in ("M01", "P006", "syn01", ""):
            with self.assertRaises(NotSynthetic): X.index_study(self.B, sid, write=True)
        self.assertEqual(tree(self.B), before)

    def test_generator_refuses_a_real_looking_folder(self):
        os.makedirs(os.path.join(self.B, "review")); open(os.path.join(self.B, "review", "M01_candidates.csv"), "w").close()
        with self.assertRaises(PermissionError): S.write_study(self.B, "SYN01")
        self.assertFalse(os.path.exists(os.path.join(self.B, MARKER)))
        with self.assertRaises(ValueError): S.write_study(tempfile.mkdtemp(), "M01")


class TestIndex(Base):
    def test_clean_study_record(self):
        S.write_study(self.B, "SYN01"); before = tree(self.B)
        r = X.index_study(self.B, "SYN01", write=True)
        self.assertEqual(r["status"], "ok"); self.assertEqual(r["usable_channels"], ["swi", "phase", "flair", "labels", "pial_sd"])
        self.assertTrue(r["synthetic"]); self.assertTrue(r["inputs_unchanged"]); self.assertEqual(r["pinned_sources_problems"], [])
        self.assertEqual(r["anatomy_source"], "T1"); self.assertEqual(r["acquisition"]["sequence"], "SWI")
        sw = r["channels"]["swi"]
        for k in ("sha256", "size", "header", "gate"): self.assertIn(k, sw)
        for k in ("affine", "affine_sha", "zooms_mm", "qform_code", "sform_code", "axcodes", "obliquity_deg", "world_centre_mm"):
            self.assertIn(k, sw["header"])
        for k in ("swi2t1", "flair2swi"): self.assertEqual(r["registration"][k]["status"], "ok")
        self.assertEqual(r["registration"]["reg_json"]["method"], "bbregister")
        after = tree(self.B); new = set(after) - set(before)
        self.assertEqual(new, {"unified_engine/image_index/SYN01.json"})                       # the only file written
        self.assertEqual({k: v for k, v in after.items() if k in before}, before)              # nothing else touched
        self.assertEqual(X.verify_index(r["path"]), (True, "ok"))

    def test_deterministic(self):
        S.write_study(self.B, "SYN01")
        self.assertEqual(X.index_study(self.B, "SYN01")["index_sha"], X.index_study(self.B, "SYN01")["index_sha"])

    def test_tampered_index_detected(self):
        S.write_study(self.B, "SYN01"); p = X.index_study(self.B, "SYN01", write=True)["path"]
        with open(p) as f: j = json.load(f)
        j["channels"]["flair"]["status"] = "ok_EDITED"
        with open(p, "w") as f: json.dump(j, f)
        self.assertFalse(X.verify_index(p)[0])

    def test_missing_channels_are_absent_not_zero(self):
        S.write_study(self.B, "SYN01", channels=("swi",), t1_route=False)
        r = X.index_study(self.B, "SYN01")
        self.assertEqual(r["status"], "ok"); self.assertEqual(r["usable_channels"], ["swi"])
        for c in ("phase", "flair", "labels", "pial_sd"):
            self.assertEqual(r["channels"][c]["status"], "missing"); self.assertNotIn("sha256", r["channels"][c])
        self.assertEqual(r["anatomy_source"], "SWI-only"); self.assertEqual(r["registration"]["swi2t1"]["status"], "missing")

    def test_stale_offgrid_misregistered_channels(self):
        p = S.write_study(self.B, "SYN01", flair_shift_mm=(0, 0, 2.6))
        S.make_older(p["pial_sd"], p["swi"])
        img = S.nib.load(p["phase"]); A = img.affine.copy(); A[0, 3] += 0.5
        S.nib.save(S.nib.Nifti1Image(S.np.asanyarray(img.dataobj), A), p["phase"])
        r = X.index_study(self.B, "SYN01"); c = r["channels"]
        self.assertEqual(c["pial_sd"]["status"], "stale"); self.assertEqual(c["phase"]["status"], "off_grid")
        self.assertEqual(c["flair"]["status"], "misregistered"); self.assertAlmostEqual(c["flair"]["residual_shift"]["shift_mm"], 2.6, delta=0.35)
        self.assertEqual(r["usable_channels"], ["swi", "labels"])

    def test_registration_state_propagates(self):
        p = S.write_study(self.B, "SYN01", reg_cost=0.95)
        S.make_older(p["flair2swi"], p["swi"])
        r = X.index_study(self.B, "SYN01")
        self.assertEqual(r["channels"]["labels"]["status"], "low_confidence")          # T1 route, cost above css_qc's threshold
        self.assertEqual(r["channels"]["flair"]["status"], "stale")                    # its LTA is older than the SWI
        os.remove(p["swi2t1"]); r = X.index_study(self.B, "SYN01")
        self.assertEqual(r["channels"]["labels"]["status"], "registration_invalid")

    def test_refused_swi_makes_nothing_usable(self):
        S.write_study(self.B, "SYN01", axcodes="SAR"); r = X.index_study(self.B, "SYN01")
        self.assertEqual(r["status"], "geometry_refused"); self.assertEqual(r["usable_channels"], [])
        self.assertTrue(all(v["status"] == "geometry_refused" for v in r["channels"].values()))

    def test_acquisition_whitelist(self):
        S.write_study(self.B, "SYN01", acquisition=dict(Manufacturer="SYNTHETIC", ImageType=["ORIGINAL", "M", "SWI"], EchoTime=0.02,
                                                        PatientName="SHOULD_NOT_APPEAR", AcquisitionDateTime="2026-01-01T00:00:00"))
        txt = json.dumps(X.index_study(self.B, "SYN01"))
        self.assertNotIn("SHOULD_NOT_APPEAR", txt); self.assertNotIn("2026-01-01", txt)

    def test_cli(self):
        cli = os.path.join(_common.ENGINE, "run_imaging.py"); env = dict(os.environ, CSS_BASE=self.B)
        r = subprocess.run([sys.executable, cli, "demo", self.B, "--n", "2"], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([sys.executable, cli, "index", "SYN02", "--base", self.B, "--write"], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("SYN02: ok", r.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.B, "unified_engine", "image_index", "SYN02.json")))
        r = subprocess.run([sys.executable, cli, "index", "M01", "--base", self.B], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 3); self.assertIn("refused", r.stderr)


if __name__ == "__main__":
    unittest.main()
