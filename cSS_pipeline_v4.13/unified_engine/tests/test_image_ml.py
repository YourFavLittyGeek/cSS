"""Stage 2 prototype: Image ML model + local inference - training, reproducibility, model health, invalid images, missing patches, model
failures, synthetic-only policy, inputs unchanged, offline (synthetic data only)."""
import json, os, shutil, subprocess, sys, tempfile, unittest
import numpy as np
import _common
from uengine.imaging import NotSynthetic, image_infer as INF, image_model as IM, synthetic_cohort as C, synthetic_images as S
from uengine.imaging import train_image_model as TR

CLI = os.path.join(_common.ENGINE, "run_imaging.py")


def tree(base):
    return {os.path.relpath(os.path.join(r, f), base): os.path.getmtime(os.path.join(r, f)) for r, _, fs in os.walk(base) for f in fs}


class Fixture(unittest.TestCase):
    """one small trained model + one small synthetic cohort, shared by the tests (built once)"""
    @classmethod
    def setUpClass(cls):
        cls.W = tempfile.mkdtemp(prefix="uengine_imml_")
        cls.model = os.path.join(cls.W, "m.json")
        cls.T = TR.train(cls.model, n_train=14, n_test=8, n_null=14, n_boot=4, seed=21, workdir=os.path.join(cls.W, "train"))
        cls.B = os.path.join(cls.W, "base"); C.write_cohort(cls.B, n=3, seed=5, profile_override=dict(slice_mm=1.2, ghost=0.0, snr=30.0))

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.W, ignore_errors=True)


class TestModel(Fixture):
    def test_health_and_card(self):
        h = IM.health(self.model); self.assertEqual(h["status"], "ok", h["reasons"]); self.assertEqual(h["data_kind"], "synthetic")
        card = h["card"]; self.assertEqual(card["training"]["data_kind"], "synthetic"); self.assertIn("SYNTHETIC", card["stamp"])
        for k in ("cv_train_cohort", "independent_synthetic_test", "negative_control_independent", "negative_control_cv"): self.assertIn(k, card["evaluation"])

    def test_signal_learned_and_negative_control_null(self):
        ev = self.T["card"]["evaluation"]
        lo, hi = ev["independent_synthetic_test"]["auc_pooled_ci95"]; self.assertGreater(lo, 0.6)               # signal: CI above chance
        lo, hi = ev["negative_control_independent"]["auc_pooled_ci95"]; self.assertLessEqual(lo, 0.5); self.assertGreaterEqual(hi, 0.5)  # null: CI contains 0.5

    def test_reproducible_prediction(self):
        m1, _ = IM.load(self.model); m2, _ = IM.load(self.model)
        X = np.random.default_rng(0).normal(size=(5, len(IM.FEATURES)))
        self.assertEqual(m1.predict(X), m2.predict(X))
        P = m1.proba(X); np.testing.assert_allclose(P.sum(1), 1.0, atol=1e-9)

    def test_corrupt_edited_incompatible_missing(self):
        d = tempfile.mkdtemp()
        try:
            self.assertEqual(IM.health(os.path.join(d, "none.json"))["status"], "missing")
            p = os.path.join(d, "x.json")
            with open(p, "w") as f: f.write("{not json")
            self.assertEqual(IM.health(p)["status"], "corrupt")
            with open(self.model) as f: J = json.load(f)
            J["params"]["W"][0][0] += 1.0
            with open(p, "w") as f: json.dump(J, f)
            self.assertEqual(IM.health(p)["status"], "corrupt")
            with open(self.model) as f: J = json.load(f)
            J["card"]["data_kind"] = "clinical"
            with open(p, "w") as f: json.dump(J, f)
            self.assertEqual(IM.health(p)["status"], "corrupt")                                         # card edits break the hash
            J["model_hash"] = IM.content_hash(J["params"], J["card"])                                   # even with a recomputed hash ...
            with open(p, "w") as f: json.dump(J, f)
            h = IM.health(p); self.assertEqual(h["status"], "incompatible"); self.assertIn("data_kind", " ".join(h["reasons"]))   # ... the training record disagrees
            with self.assertRaises(ValueError): IM.load(p)
            with open(self.model) as f: J = json.load(f)
            J["card"]["evaluation"]["independent_synthetic_test"]["auc_pooled"] = 0.5
            with open(p, "w") as f: json.dump(J, f)
            self.assertEqual(IM.health(p)["status"], "corrupt")
            with self.assertRaises(FileExistsError): IM.ImageModel().save(self.model, {})                  # never overwritten
        finally: shutil.rmtree(d)

    def test_feature_set_change_is_incompatible(self):
        old = list(IM.FEATURES)
        try:
            IM.FEATURES.append("new_feature"); h = IM.health(self.model)
            self.assertEqual(h["status"], "incompatible"); self.assertIn("feature set", " ".join(h["reasons"]))
        finally: IM.FEATURES[:] = old


class TestInference(Fixture):
    def test_inference_record(self):
        before = tree(self.B)
        r = INF.run_study(self.B, "SYN001", model_path=self.model, write=True)
        self.assertTrue(r["synthetic"]); self.assertTrue(r["experimental"]); self.assertIn("SYNTHETIC", r["stamp"])
        self.assertTrue(r["model"]["applied"]); self.assertEqual(r["model"]["data_kind"], "synthetic"); self.assertTrue(r["original_inputs_unchanged"])
        ok = [c for c in r["candidates"] if c["status"] == "ok"]; self.assertTrue(ok)
        for c in ok:
            self.assertAlmostEqual(sum(c["class_probabilities"].values()), 1.0, places=3)
            self.assertLessEqual(c["p_css_interval"][0], c["p_css_interval"][1])
            self.assertIn(c["category"], ("likely_cSS", "uncertain", "unlikely_cSS"))
            self.assertEqual(c["confidence"], max(c["class_probabilities"].values()))
            for k in ("vox_ijk", "world_centre_mm", "cand_uid", "patch_sha", "previews", "features"): self.assertIn(k, c)
            g = np.array(c["previews"]["surface_uv"]["gray"]); self.assertTrue(((g >= 0) & (g <= 255)).all())
        new = {k for k in tree(self.B) if k not in before}
        self.assertTrue(all(k.startswith(("unified_engine/image_ml/", "unified_engine/patches/")) for k in new), new)
        self.assertIn("unified_engine/image_ml/SYN001.json", new)
        self.assertEqual(INF.run_study(self.B, "SYN001", model_path=self.model)["candidates"][0].get("p_css"), r["candidates"][0].get("p_css"))

    def test_predictions_track_truth_on_synthetic_data(self):
        hits = n = 0
        for sid in ("SYN001", "SYN002", "SYN003"):
            r = INF.run_study(self.B, sid, model_path=self.model)
            import csv
            with open(os.path.join(self.B, "unified_engine", "image_truth", f"{sid}.csv")) as f: T = {(t["list"], int(t["obj_id"])): t["kind"] for t in csv.DictReader(f)}
            for c in r["candidates"]:
                if c["status"] == "ok": n += 1; hits += (c["p_css"] >= 0.5) == (T[(c["list"], int(c["obj_id"]))] == "css")
        self.assertGreater(n, 8); self.assertGreater(hits / n, 0.75)

    def test_invalid_images_not_scorable(self):
        b = os.path.join(self.W, "bad"); S.write_study(b, "SYN010", axcodes="SAR")               # array axis 2 not S-I
        r = INF.run_study(b, "SYN010", model_path=self.model)
        self.assertTrue(r["candidates"]); self.assertTrue(all(c["status"] == "not_scorable" for c in r["candidates"]))
        self.assertIn("geometry_refused", r["study"]["blocked"])
        b2 = os.path.join(self.W, "thick"); C.write_study(b2, "SYN011", C.sample_profile(np.random.default_rng(0), slice_mm=3.0),
                                                           C.sample_objects(np.random.default_rng(1), 1, 2))
        r = INF.run_study(b2, "SYN011", model_path=self.model); self.assertIn("quality_refused", r["study"]["blocked"])
        b3 = os.path.join(self.W, "corruptimg"); p = S.write_study(b3, "SYN012")
        with open(p["swi"], "wb") as f: f.write(b"not a nifti")
        with self.assertRaises(Exception): INF.run_study(b3, "SYN012", model_path=self.model)                 # unreadable image: fails loudly

    def test_missing_patches_reported(self):
        b = os.path.join(self.W, "tiny"); S.write_study(b, "SYN020")                              # contains a 2-voxel object
        r = INF.run_study(b, "SYN020", model_path=self.model)
        t = next(c for c in r["candidates"] if c["ref"] == "x2"); self.assertEqual(t["status"], "no_patch"); self.assertIn("< 3", t["reason"])
        self.assertNotIn("p_css", t)
        b2 = os.path.join(self.W, "nopial"); S.write_study(b2, "SYN021", channels=("swi", "flair", "labels"))
        r = INF.run_study(b2, "SYN021", model_path=self.model)
        self.assertTrue(all(c["status"] == "not_scorable" and "no surface frame" in c["reason"] for c in r["candidates"]))

    def test_missing_or_bad_model_withholds_predictions(self):
        r = INF.run_study(self.B, "SYN002", model_path=os.path.join(self.W, "absent.json"))
        self.assertFalse(r["model"]["applied"]); self.assertTrue(all(c["status"] in ("model_unavailable", "no_patch", "not_scorable") for c in r["candidates"]))
        self.assertTrue(any(c["status"] == "model_unavailable" for c in r["candidates"]))
        self.assertFalse(any("p_css" in c for c in r["candidates"]))

    def test_model_failure_writes_nothing_and_keeps_previous_result(self):
        INF.run_study(self.B, "SYN003", model_path=self.model, write=True)
        p = os.path.join(self.B, "unified_engine", "image_ml", "SYN003.json")
        with open(p, "rb") as f: prev = f.read()
        env = dict(os.environ, CSS_IMAGE_ENGINE_FAIL="1")
        r = subprocess.run([sys.executable, CLI, "infer", "SYN003", "--base", self.B, "--model", self.model, "--write"], env=env,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 4); self.assertIn("simulated image model failure", r.stderr)
        with open(p, "rb") as f: self.assertEqual(f.read(), prev)

    def test_synthetic_only(self):
        d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "review")); before = tree(d)
        try:
            with self.assertRaises(NotSynthetic): INF.run_study(d, "SYN001", model_path=self.model, write=True)
            with self.assertRaises(NotSynthetic): INF.run_study(self.B, "M01", model_path=self.model, write=True)
            self.assertEqual(tree(d), before)
            r = subprocess.run([sys.executable, CLI, "infer", "M01", "--base", self.B], capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 3)
        finally: shutil.rmtree(d)

    def test_bundled_model_is_healthy_and_selected(self):
        ms = INF.list_models(None); self.assertTrue(ms)
        self.assertTrue(any(m["status"] == "ok" and m["data_kind"] == "synthetic" for m in ms), ms)
        p, h = INF.select_model(self.B); self.assertEqual(h["status"], "ok"); self.assertTrue(p.startswith(INF.BUNDLED))

    def test_offline_no_network_connection(self):
        """the repository's netguard (tests/netguard) refuses and logs every non-loopback connection; inference must succeed with an empty log"""
        log = os.path.join(self.W, "netguard.log"); guard = os.path.join(os.path.dirname(_common.ENGINE), "tests", "netguard")
        env = dict(os.environ, PYTHONPATH=guard, CSS_NETGUARD_LOG=log)
        r = subprocess.run([sys.executable, CLI, "infer", "SYN001", "--base", self.B, "--model", self.model], env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        if os.path.exists(log):
            with open(log) as f: self.assertEqual(f.read().strip(), "", "inference attempted a network connection")
        probe = subprocess.run([sys.executable, "-c", "import socket; s=socket.socket(); s.connect(('192.0.2.1', 9))"], env=env, capture_output=True, text=True, timeout=30)
        self.assertIn("netguard: blocked", probe.stderr)                                    # the guard really is active in this environment
        with open(log) as f: self.assertEqual(len(f.read().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
