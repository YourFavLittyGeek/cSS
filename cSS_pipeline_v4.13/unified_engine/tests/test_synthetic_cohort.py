"""Stage 2 P3: parametric synthetic cohort - truth recovered, acquisition physics, reader label noise, quality cases, negative control,
re-check of the provisional P1 residual-shift thresholds (synthetic data only)."""
import collections, csv, json, os, shutil, tempfile, unittest
import numpy as np
import _common  # noqa: F401
from uengine.imaging import patches as PT, synthetic_cohort as C


def _obj(kind, rng_seed=0, **kw):
    o = C.sample_objects(np.random.default_rng(rng_seed), int(kind == "css"), int(kind != "css"), None if kind == "css" else [kind])[0]
    o.update(kw); return o


def _prof(**kw):
    base = dict(vendor="SYNTH-A", field_T=3.0, TE_ms=20.0, inplane_mm=0.8, slice_mm=1.2, snr=30.0, bias=0.0, ghost=0.0, tilt_deg=0.0,
                axcodes="RAS", sequence="SWI", flair=True, flair_shift_mm=0.0)
    base.update(kw); return C.sample_profile(np.random.default_rng(0), **base)


class TestPhysics(unittest.TestCase):
    def test_every_kind_is_rendered_dark_where_it_should_be(self):
        for kind in C.KINDS:
            R = C.render(_prof(), [_obj(kind)], seed=1); w = R["weights"][0]
            self.assertGreater(int((w >= 0.5).sum()), 0, kind)
            con = C.measured_contrast(R["arrays"]["swi"], w, R["brain"], R["vox"])
            self.assertLess(con, 0.95 if kind == "normal_iron_cortex" else 0.85, kind)          # darker than its surroundings

    def test_phase_sign_follows_source_and_vendor(self):
        for vendor, s in (("SYNTH-A", 1), ("SYNTH-B", -1)):
            for kind, src in (("microbleed", -1), ("css", -1), ("calcification", 1)):
                R = C.render(_prof(vendor=vendor, snr=60), [_obj(kind)], seed=2); m = R["weights"][0] >= 0.5
                self.assertEqual(np.sign(R["arrays"]["phase"][m].mean()), src * s, (vendor, kind))   # calcium opposite to haemosiderin

    def test_blooming_grows_with_echo_time_and_field(self):
        o = _obj("microbleed", radius_mm=1.0)
        v = [int((C.render(_prof(TE_ms=te, field_T=f, snr=80), [o], seed=3)["weights"][0] >= 0.5).sum()) for te, f in ((10, 1.5), (20, 3.0), (40, 3.0))]
        self.assertLess(v[0], v[1]); self.assertLess(v[1], v[2])

    def test_thick_slices_dilute_thin_sheets(self):
        o = _obj("css", depth_mm=0.9)
        c = [C.measured_contrast(*(lambda R: (R["arrays"]["swi"], R["weights"][0], R["brain"], R["vox"]))(C.render(_prof(slice_mm=s, snr=80, TE_ms=10), [o], seed=4)))
             for s in (1.0, 2.5)]
        self.assertTrue(c[1] is None or c[1] > c[0])                                            # less contrast (or invisible) at 2.5 mm

    def test_noise_and_bias(self):
        R = C.render(_prof(snr=20, bias=0.0), [], seed=5); wm = R["arrays"]["labels"] == 2
        est = float(np.std(R["arrays"]["swi"][wm] - C.render(_prof(snr=1e6, bias=0.0), [], seed=5)["arrays"]["swi"][wm]))
        self.assertAlmostEqual(est / R["sigma"], 1.0, delta=0.15)
        Rb = C.render(_prof(snr=1e6, bias=0.3), [], seed=5); R0 = C.render(_prof(snr=1e6, bias=0.0), [], seed=5)
        ratio = Rb["arrays"]["swi"][R0["brain"]] / R0["arrays"]["swi"][R0["brain"]]
        self.assertGreater(float(np.ptp(ratio)), 0.15); np.testing.assert_allclose(ratio, Rb["bias_field"][R0["brain"]], rtol=1e-3)

    def test_quality_truth(self):
        self.assertTrue(_prof(ghost=0.4)["insufficient_quality"]); self.assertTrue(_prof(snr=6.0)["insufficient_quality"])
        self.assertFalse(_prof()["insufficient_quality"])


class TestCohort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = tempfile.mkdtemp(prefix="uengine_p3_"); cls.r = C.write_cohort(cls.B, n=6, seed=7)

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.B, ignore_errors=True)

    def test_files_tables_and_truth_separation(self):
        for sid in self.r["profiles"]:
            for rel in (f"data/{sid}_swi.nii", f"data/{sid}_phase.nii.gz", f"work/{sid}_pial_sd.nii.gz", f"review/{sid}_candidates.csv",
                        f"raw/{sid}/SWI/{sid}_swi.json"):
                self.assertTrue(os.path.exists(os.path.join(self.B, rel)), rel)
            with open(os.path.join(self.B, f"review/{sid}_candidates.csv")) as f: hdr = f.readline()
            for word in ("kind", "class", "truth", "css", "vein"): self.assertNotIn(word, hdr)          # no label in the detector-like table
        with open(os.path.join(self.B, "unified_engine", "image_truth", "cohort.json")) as f: meta = json.load(f)
        self.assertTrue(meta["synthetic"]); self.assertIn("not clinical", meta["note"])

    def test_truth_recovered_through_the_pipeline(self):
        n = 0
        for sid in self.r["profiles"]:
            E = PT.extract_study(self.B, sid)
            with open(os.path.join(self.B, "unified_engine", "image_truth", f"{sid}.csv")) as f: T = {(t["list"], int(t["obj_id"])): t for t in csv.DictReader(f)}
            for (lst, oid), a in E["patches"].items():
                t = T[(lst, oid)]; self.assertEqual(int(a["object_mask"].any()), 1); n += 1
                self.assertEqual(json.loads(a["metadata_json"])["cand_uid"], t["cand_uid"])
        self.assertGreater(n, 15)

    def test_reproducible(self):
        b2 = tempfile.mkdtemp(); r2 = C.write_cohort(b2, n=6, seed=7)
        try:
            for sid in self.r["profiles"]:
                for rel in (f"data/{sid}_swi.nii", f"review/{sid}_candidates.csv"):
                    with open(os.path.join(self.B, rel), "rb") as a, open(os.path.join(b2, rel), "rb") as b: self.assertEqual(a.read(), b.read(), rel)
            self.assertEqual(self.r["readers"], r2["readers"])
        finally: shutil.rmtree(b2, ignore_errors=True)

    def test_reader_rows_use_the_v2_schema(self):
        for r in self.r["readers"]:
            self.assertEqual(r["label_schema_version"], "css-labels/2.0")
            self.assertIn(r["primary_class"], ("definite_css", "definite_mimic", "indeterminate", "insufficient_quality", "out_of_scope"))
            if r["primary_class"] == "definite_mimic": self.assertIn(r["mimic_subtype"], C.MIMICS)
            if r["primary_class"] == "insufficient_quality": self.assertIn(r["quality_reason"], ("motion", "noise"))


class TestReaders(unittest.TestCase):
    def fake(self, n=4000, kind="css", con=0.3, nvox=40, bad=False):
        prof = dict(snr=30.0, ghost=0.4 if bad else 0.0, insufficient_quality=bad)
        T = [dict(study_id="SYN001", list="candidates", obj_id=i, cand_uid=f"u{i}", kind=kind, primary_class=C.KINDS[kind][0],
                  mimic_subtype=C.KINDS[kind][1], measured_contrast=con, n_vox=nvox, rendered=True) for i in range(n)]
        return T, {"SYN001": prof}

    def test_error_and_indeterminate_rates_match_the_model(self):
        T, P = self.fake(); rows = C.simulate_readers(T, P, seed=3)
        for rid, rd in C.READERS.items():
            R = [r for r in rows if r["reader_id"] == rid]; dif = R[0]["difficulty"]
            p_ind = rd["base_indet"] + 0.5 * dif; p_err = (1 - p_ind) * (rd["base_error"] + 0.4 * dif)
            ind = np.mean([r["primary_class"] == "indeterminate" for r in R]); err = np.mean([r["primary_class"] not in ("definite_css", "indeterminate") for r in R])
            self.assertAlmostEqual(ind, p_ind, delta=4 * np.sqrt(p_ind * (1 - p_ind) / len(R)) + 1e-3, msg=rid)
            self.assertAlmostEqual(err, p_err, delta=4 * np.sqrt(p_err * (1 - p_err) / len(R)) + 1e-3, msg=rid)
            wrong = collections.Counter(r["mimic_subtype"] for r in R if r["primary_class"] == "definite_mimic")
            self.assertEqual(set(wrong), {"vein_surface", "normal_iron_cortex", "artifact_airbone"})        # only the configured confusions

    def test_difficulty_raises_indeterminate(self):
        e = C.simulate_readers(*self.fake(con=0.2, nvox=60), seed=1); h = C.simulate_readers(*self.fake(con=0.9, nvox=4), seed=1)
        ind = lambda R: np.mean([r["primary_class"] == "indeterminate" for r in R])
        self.assertGreater(ind(h), ind(e) + 0.2)

    def test_insufficient_quality_concentrated_in_bad_studies(self):
        q = lambda R: np.mean([r["primary_class"] == "insufficient_quality" for r in R])
        self.assertGreater(q(C.simulate_readers(*self.fake(bad=True), seed=2)), 0.8); self.assertEqual(q(C.simulate_readers(*self.fake(), seed=2)), 0.0)


class TestNegativeControl(unittest.TestCase):
    def test_signal_zero_images_are_independent_of_labels(self):
        rng = np.random.default_rng(9); objs = C.sample_objects(rng, 3, 5)
        R = C.render(_prof(), objs, seed=1, signal=0)
        self.assertTrue(all(o["kind"] == objs[i]["kind"] for i, o in enumerate(R["objects"])))          # labels unchanged
        rk = [C.render(_prof(), objs, seed=s, signal=0)["objects"] for s in range(30)]
        css_rendered = [o["rendered_kind"] for objs_ in rk for o in objs_ if o["kind"] == "css"]
        mim_rendered = [o["rendered_kind"] for objs_ in rk for o in objs_ if o["kind"] != "css"]
        f = lambda L: np.mean([k == "css" for k in L])
        self.assertLess(abs(f(css_rendered) - f(mim_rendered)), 0.15)                                    # rendered kind does not depend on the label


class TestThresholdRecheck(unittest.TestCase):
    def test_residual_shift_thresholds_on_varied_acquisitions(self):
        rng = np.random.default_rng(11); profs = {f"p{i}": C.sample_profile(rng, slice_mm=s, snr=snr, bias=b)
                                                   for i, (s, snr, b) in enumerate([(1.0, 30, 0.0), (1.5, 12, 0.3), (2.0, 20, 0.15), (2.5, 10, 0.3)])}
        rows = C.shift_recheck(profs, [0.0, 3.5])
        for r in rows:
            if r["true_shift_mm"] == 0.0: self.assertNotEqual(r["status"], "misregistered", r)
            else: self.assertEqual(r["status"], "misregistered", r)


if __name__ == "__main__":
    unittest.main()
