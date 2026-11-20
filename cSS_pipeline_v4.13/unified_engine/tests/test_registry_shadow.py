"""model registry (loading, versioning, health, compatibility) and the SHADOW runner (fallbacks, separation, no modification)"""
import glob, hashlib, json, os, shutil, tempfile, unittest
import numpy as np, pandas as pd
import _common
from uengine import registry, shadow, demo_base, provenance as pv
from uengine.prototype.fusion import UnifiedScorer

def _w(p, obj):
    with open(p, "w") as f: json.dump(obj, f)


def _t(p, s):
    with open(p, "w") as f: f.write(s)


def _r(p):
    with open(p) as f: return json.load(f)


MODEL = os.path.join(_common.ENGINE, "models", "synthetic_demo_offset_v1.0.0.json")


def tree_hashes(d, skip=("unified_engine/shadow",)):
    out = {}
    for f in glob.glob(os.path.join(d, "**", "*"), recursive=True):
        rel = os.path.relpath(f, d)
        if os.path.isfile(f) and not any(rel.startswith(s) for s in skip):
            with open(f, "rb") as fh: out[rel] = hashlib.sha256(fh.read()).hexdigest()
    return out


class TestRegistry(unittest.TestCase):
    def setUp(self): self.t = tempfile.mkdtemp(prefix="uengine_reg_")
    def tearDown(self): shutil.rmtree(self.t, ignore_errors=True)

    def test_bundled_model_healthy(self):
        h = registry.health(MODEL)
        self.assertEqual(h["status"], "ok", h["reasons"]); self.assertEqual(h["data_kind"], "synthetic"); self.assertEqual(h["mode"], "offset")
        self.assertEqual(registry.active()["path"], MODEL)
        self.assertEqual(h["card"]["intended_use"].split()[0], "software")

    def test_missing_corrupt_incompatible(self):
        self.assertEqual(registry.health(os.path.join(self.t, "none.json"))["status"], "missing")
        p = os.path.join(self.t, "bad.json"); _t(p, "{not json"); self.assertEqual(registry.health(p)["status"], "corrupt")
        with open(MODEL) as f: d = json.load(f)
        e = json.loads(json.dumps(d)); e["params"]["past"]["beta"][2] += 1.0; q = os.path.join(self.t, "edited.json"); _w(q, e)
        self.assertEqual(registry.health(q)["status"], "corrupt")                       # content no longer matches its hash
        c = json.loads(json.dumps(d)); c["card"]["data_kind"] = "clinical"; q = os.path.join(self.t, "relabelled.json"); _w(q, c)
        self.assertEqual(registry.health(q)["status"], "incompatible")                  # card cannot relabel a synthetic model
        s = json.loads(json.dumps(d)); s["params"]["schema_sha256"] = "0" * 64
        import hashlib as hl; s["model_hash"] = hl.sha256(json.dumps(s["params"], sort_keys=True, default=str).encode()).hexdigest()
        q = os.path.join(self.t, "schema.json"); _w(q, s); h = registry.health(q)
        self.assertEqual(h["status"], "incompatible"); self.assertTrue(any("schema" in r for r in h["reasons"]))
        v = json.loads(json.dumps(d)); v["params"]["prototype"] = "uengine-fusion/2.0"
        v["model_hash"] = hl.sha256(json.dumps(v["params"], sort_keys=True, default=str).encode()).hexdigest()
        q = os.path.join(self.t, "ver.json"); _w(q, v); self.assertEqual(registry.health(q)["status"], "incompatible")

    def test_never_overwrites_and_policy(self):
        with self.assertRaises(FileExistsError): registry.save_with_card(UnifiedScorer("math_only"), MODEL, {})
        h = registry.health(MODEL)
        self.assertEqual(registry.apply_policy(h, True)[0], True)
        ok, why = registry.apply_policy(h, False); self.assertFalse(ok); self.assertIn("never applied to a real study", why)
        self.assertFalse(registry.apply_policy(dict(status="corrupt", reasons=["x"]), True)[0])

    def test_configured_model_and_user_dir(self):
        os.makedirs(os.path.join(self.t, "unified_engine", "models"))
        _w(os.path.join(self.t, "unified_engine", "config.json"), dict(active_model="does_not_exist"))
        self.assertEqual(registry.active(self.t)["status"], "missing")
        os.remove(os.path.join(self.t, "unified_engine", "config.json"))
        _t(os.path.join(self.t, "unified_engine", "models", "broken.json"), "x")
        ms = registry.list_models(self.t); self.assertEqual({m["status"] for m in ms}, {"corrupt", "ok"})
        self.assertEqual(registry.active(self.t)["status"], "ok")                        # a broken user model never becomes active


class TestShadow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = tempfile.mkdtemp(prefix="uengine_shadow_"); cls.codes = demo_base.write(cls.B, n_patients=5, seed=901)

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.B, ignore_errors=True)

    def test_synthetic_applied_and_separated(self):
        before = tree_hashes(self.B)
        r = shadow.run_study(self.B, "SYN01", synthetic=True)
        self.assertTrue(r["ml_applied"]); self.assertTrue(r["shadow_mode"]); self.assertTrue(r["original_outputs_unchanged"])
        self.assertEqual(tree_hashes(self.B), before)                                   # nothing outside unified_engine/shadow written
        self.assertTrue(os.path.exists(os.path.join(self.B, "unified_engine", "shadow", "SYN01.json")))
        for c in r["candidates"]:
            self.assertEqual(set(c) >= {"deterministic", "characteristics", "ml", "unified", "trace"}, True)
            self.assertEqual(c["trace"]["model_hash"], r["model"]["model_hash"])
        cand = pd.read_csv(os.path.join(self.B, "review", "SYN01_candidates.csv"))
        got = {c["ref"]: c["deterministic"]["score_v4"] for c in r["candidates"] if c["list"] == "shown"}
        for _, row in cand.iterrows(): self.assertAlmostEqual(got[f"c{int(row.cand_id)}"], row.score_v4)     # existing output reproduced exactly
        self.assertEqual(r["deterministic_patient_score"]["total"], _r(os.path.join(self.B, "review", "SYN01_score.json"))["multifocality_0_4"])

    def test_real_study_never_gets_the_synthetic_model(self):
        r = shadow.run_study(self.B, "SYN02", synthetic=False, write=False)
        self.assertFalse(r["ml_applied"]); self.assertIn("never applied to a real study", r["ml_status"])
        for c in r["candidates"]:
            self.assertEqual(c["unified"]["source"], "deterministic_fallback"); self.assertIsNone(c["unified"]["p"])
            self.assertIsNotNone(c["deterministic"]["score_v4"])

    def test_ml_failure_falls_back(self):
        t = tempfile.mkdtemp(); bad = os.path.join(t, "m.json"); _t(bad, "{}")
        r = shadow.run_study(self.B, "SYN03", synthetic=True, model_path=bad, write=False)
        self.assertFalse(r["ml_applied"]); self.assertTrue(all(c["unified"]["source"] == "deterministic_fallback" for c in r["candidates"]))
        orig = shadow.UnifiedScorer.predict                                    # crash INSIDE ML scoring (model healthy, applied)
        try:
            shadow.UnifiedScorer.predict = lambda self, df, data_kind="synthetic": (_ for _ in ()).throw(RuntimeError("simulated crash"))
            r = shadow.run_study(self.B, "SYN03", synthetic=True, write=False)
        finally: shadow.UnifiedScorer.predict = orig
        self.assertFalse(r["ml_applied"]); self.assertIn("simulated crash", r["ml_error"]); self.assertIn("ml_traceback", r)

    def test_corrupted_rows_and_missing_lists(self):
        t = tempfile.mkdtemp(); shutil.copytree(os.path.join(self.B, "review"), os.path.join(t, "review"))
        open(os.path.join(t, demo_base.MARKER.replace("unified_engine/", "")), "w").close()
        p = os.path.join(t, "review", "SYN04_candidates.csv"); d = pd.read_csv(p)
        d["darkness_z"] = d["darkness_z"].astype(object); d.loc[0, "darkness_z"] = "garbage"; d.loc[1, "cortex_frac"] = 7.0; d.loc[2, "tram_frac"] = np.nan; d.to_csv(p, index=False)
        r = shadow.run_study(t, "SYN04", synthetic=True, write=False)
        self.assertEqual(r["input_validation"]["corrupt"].get("darkness_z"), 1); self.assertEqual(r["input_validation"]["out_of_range"].get("cortex_frac"), 1)
        c0 = r["candidates"][0]; self.assertEqual(c0["characteristics"]["status"]["darkness_z"], "corrupt")
        self.assertEqual(c0["unified"]["category"], "uncertain")
        with self.assertRaises(FileNotFoundError): shadow.run_study(t, "SYN99", synthetic=True, write=False)

    def test_patient_keys_and_registration(self):
        os.makedirs(os.path.join(self.B, "unified_engine"), exist_ok=True)
        pd.DataFrame([dict(exam_id="SYN05", patient_key="SYNP-A")]).to_csv(os.path.join(self.B, "unified_engine", "patient_keys.csv"), index=False)
        r = shadow.run_study(self.B, "SYN05", synthetic=True, write=False)
        self.assertEqual((r["patient_key"], r["patient_key_verified"]), ("SYNP-A", True))
        self.assertEqual(shadow.registration_state(dict(anatomy="T1", label_shift_mm=0.8)), "marginal")
        self.assertEqual(shadow.registration_state(dict(anatomy="SWI-only", label_shift_mm=0.1)), "swi_only")
        self.assertEqual(shadow.registration_state({}), "unverified")

    def test_reproducible(self):
        a = shadow.run_study(self.B, "SYN01", synthetic=True, write=False); b = shadow.run_study(self.B, "SYN01", synthetic=True, write=False)
        self.assertEqual([c["unified"]["p"] for c in a["candidates"]], [c["unified"]["p"] for c in b["candidates"]])

    def test_demo_base_refuses_a_real_folder_and_has_no_labels(self):
        t = tempfile.mkdtemp(); os.makedirs(os.path.join(t, "review")); _t(os.path.join(t, "review", "M02_candidates.csv"), "x")
        with self.assertRaises(RuntimeError): demo_base.write(t)
        cols = set(pd.read_csv(os.path.join(self.B, "review", "SYN01_candidates.csv")).columns)
        self.assertFalse(cols & {"y", "y_true", "cls", "fate", "patient_key"})


if __name__ == "__main__":
    unittest.main()
