"""2026-11-25 missed-cSS plan steps 1-4 (user decision):
1. ALBUS re-detects every expert mark: its own excluded / gate-dropped object under the mark, else the dark voxels inside the drawing;
   measured by the PRODUCTION detector (pinned sha256, file unchanged; objects forced in memory, rules recorded not applied) on a
   disposable copy - the project is never written; the reviewer confirms ALBUS's outline (own file, validated, refused in a blind read);
2. NOX learns from CONFIRMED objects only, training patients only, and only when their measurements do not reveal their origin and
   NOX predicts the candidates no worse;
3. PERCIVAL scores marks with NOX + LUMOS only (ALBUS never an input); development (out-of-fold) and locked-test recall reported apart;
4. the fate report: which rule / gate loses the marked cSS.
Synthetic phantom only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import nibabel as nib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); SCR = os.path.join(ROOT, "scripts")
for p in (os.path.join(ROOT, "app"), SCR, os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)
import albus_redetect as AR                                           # noqa: E402
from uengine import provenance as pv                                  # noqa: E402
from uengine.percival import meta as MT                               # noqa: E402
from test_lumos_missed_marks import rows_and_marks                    # noqa: E402
HTML = os.path.join(SCR, "review_web.html")


def tree_hash(d):
    h = {}
    for p in sorted(glob.glob(os.path.join(d, "**", "*"), recursive=True)):
        if os.path.isfile(p): h[os.path.relpath(p, d)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return h


class TestWrapper(unittest.TestCase):
    def test_detector_untouched_and_pinned(self):
        import albus_measure as AM
        self.assertEqual(AM.PINNED, pv.DETECTOR_SHA256)
        self.assertEqual(hashlib.sha256(open(os.path.join(SCR, "detect_css.py"), "rb").read()).hexdigest(), pv.DETECTOR_SHA256)
        src = AM.source(); self.assertIn("forced_would_exclude", src); self.assertIn("lab = _F", src)
        with mock.patch.object(AM, "PINNED", "0" * 64):
            with self.assertRaises(SystemExit): AM.source()                           # a changed detector is refused


class TestPhantom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = tempfile.mkdtemp(prefix="albus_redo_"); fs = os.path.join(cls.B, "fs"); os.makedirs(fs)
        open(os.path.join(fs, "FreeSurferColorLUT.txt"), "w").write("0 Unknown 0 0 0 0\n")
        env = dict(os.environ, CSS_BASE=cls.B, FREESURFER_HOME=fs, PYTHONWARNINGS="ignore")
        for cmd in ([os.path.join(HERE, "phantom_v4.py"), "PH3", "1"], [os.path.join(SCR, "align_seg.py"), "PH3"], [os.path.join(SCR, "detect_css.py"), "PH3"]):
            r = subprocess.run([sys.executable] + cmd, env=env, capture_output=True, text=True, timeout=900, cwd=cls.B)
            assert r.returncode == 0, r.stderr[-800:]
        cls.env = env

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.B, ignore_errors=True)

    def mark_of(self, tid):
        swi = nib.load(os.path.join(self.B, "data", "PH3_swi.nii")); T = np.asarray(nib.load(os.path.join(self.B, "work", "PH3_truth.nii.gz")).dataobj)
        can = nib.as_closest_canonical(swi); n2c = np.linalg.inv(can.affine) @ swi.affine
        v = np.argwhere(T == tid); c = np.round((n2c[:3, :3] @ v.T).T + n2c[:3, 3]).astype(int); k = int(np.median(c[:, 2])); on = c[c[:, 2] == k]
        return dict(shape="rect", plane="axial", strokes=[[[int(on[:, 0].min() - 1), int(on[:, 1].min() - 1), k], [int(on[:, 0].max() + 1), int(on[:, 1].max() + 1), k]]])

    def test_redetect_measures_with_the_detector_and_never_writes_the_project(self):
        before = tree_hash(self.B); out = tempfile.mkdtemp(prefix="albus_out_")
        marks = {"missed_1": self.mark_of(2), "missed_2": self.mark_of(5), "missed_3": dict(shape="point", strokes=[])}
        with mock.patch.dict(os.environ, {"FREESURFER_HOME": self.env["FREESURFER_HOME"]}):
            R = AR.run(self.B, "PH3", marks, out, scripts=SCR, python=sys.executable)
        self.assertEqual(tree_hash(self.B), before)                                     # the project is untouched
        self.assertEqual(R["marks"]["missed_3"]["status"], "failed")
        for k in ("missed_1", "missed_2"):
            m = R["marks"][k]; self.assertEqual(m["status"], "measured", m.get("reason"))
            for c in ("darkness_z", "pial_dist_mm", "cortex_frac", "volume_mm3", "edge_contrast"): self.assertIn(c, m["measurements"])
            self.assertTrue(m["outline"]) and self.assertRegex(m["object_sha"], r"^[0-9a-f]{16}$")
            self.assertIn("would_exclude", m)
        self.assertEqual(R["detector_sha256"], pv.DETECTOR_SHA256)
        self.assertFalse(glob.glob(os.path.join(out, "albus_PH3_*")))                  # the disposable copy is removed
        with np.load(os.path.join(out, "PH3.npz")) as z: self.assertEqual(set(z.files), {"missed_1", "missed_2"})
        self.assertEqual(AR.marks_key(marks, SCR), R["key"])


class TestReport(unittest.TestCase):
    def test_fate_categories(self):
        B = tempfile.mkdtemp(); os.makedirs(os.path.join(B, "review"))
        import pandas as pd
        pd.DataFrame(dict(missed_id=[1, 2, 3, 4, 5], reviewer="Dr A", detector_fate=[
            "overlaps shown candidate #4", "excluded object 3: E15@v5.3 skull band (x)", "below a generation gate (size / slices / shape)",
            "not generated by the detector (outside the search zone, not dark enough, or no ridge)", "excluded object 7: E15@v5.3 skull band (y)"])
                     ).to_csv(os.path.join(B, "review", "S1_missed.csv"), index=False)
        R = AR.fate_report(B, ["S1"], {"S1": dict(marks={"missed_3": dict(status="measured", gate="G1_volume")})})
        self.assertEqual(R["n_marks"], 5); self.assertEqual(R["n_missed"], 4)
        T = {(t["category"], t["cause"]): t["n"] for t in R["table"]}
        self.assertEqual(T[("excluded", "E15@v5.3 skull band")], 2); self.assertEqual(T[("gate", "G1_volume")], 1)
        self.assertEqual(sum(n for (c, _), n in T.items() if c == "not_generated"), 1)


class TestConfirmation(unittest.TestCase):
    def test_only_expert_correct_for_this_object(self):
        import percival_gui as PG
        rec = dict(status="measured", object_sha="a" * 16)
        E = lambda st, role, sha="a" * 16: dict(status=st, role=role, object_sha=sha)
        self.assertTrue(PG._confirmed(rec, {"Dr A": E("correct", "expert")}))
        self.assertFalse(PG._confirmed(rec, {"T": E("correct", "trainee")}))
        self.assertFalse(PG._confirmed(rec, {"Dr A": E("correct", "expert", "b" * 16)}))          # another object (re-detected since)
        self.assertFalse(PG._confirmed(rec, {"Dr A": E("correct", "expert"), "Dr B": E("wrong", "expert")}))
        self.assertFalse(PG._confirmed(dict(status="failed"), {"Dr A": E("correct", "expert")}))

    def test_reviewer_file_and_routes(self):
        import review_web as RW
        self.assertEqual(RW.ROUTES[("GET", "/api/albus_marks")], "refused"); self.assertEqual(RW.ROUTES[("POST", "/api/albus_confirm")], "refused")
        r = RW.albus_confirm("ARC1", "Dr Test", dict(missed_id=2, object_sha="ab" * 8, status="correct"))
        r = RW.albus_confirm("ARC1", "Dr Test", dict(missed_id=2, object_sha="ab" * 8, status="wrong"))
        self.assertEqual([(x["missed_id"], x["status"]) for x in r], [("2", "wrong")])     # the latest answer
        for bad in (dict(missed_id="x", object_sha="ab" * 8, status="correct"), dict(missed_id=2, object_sha="zz", status="correct"),
                    dict(missed_id=2, object_sha="ab" * 8, status="maybe")):
            with self.assertRaises(RW.RB.BlindError): RW.albus_confirm("ARC1", "Dr Test", bad)

    def test_char_mapping_matches_candidates(self):
        import percival_gui as PG
        with mock.patch.object(PG, "nox_feature_set", return_value=(list(MT.CHAR), "v000")):
            ch = PG._char_from(dict(volume_mm3=100.0, darkness_z=2.5, edge_contrast="", tram_frac=float("nan")), {"x2_core_contrast_nu": 3.0})
        self.assertAlmostEqual(ch["log_volume_mm3"], np.log(100.0)); self.assertEqual(ch["darkness_z"], 2.5)
        self.assertIsNone(ch["edge_contrast"]); self.assertIsNone(ch["tram_frac"]); self.assertEqual(ch["x2_core_contrast_nu"], 3.0)
        self.assertEqual(set(ch), set(MT.CHAR))


class TestLearning(unittest.TestCase):
    def marks(self, shift=0.5, reveal=False):
        rows, marks = rows_and_marks(); rng = np.random.default_rng(9)
        cm = [dict(m, char={k: float(rng.normal(shift)) + (8.0 if reveal and k == "darkness_z" else 0.0) for k in MT.CHAR}) for m in marks]
        return rows, marks, cm

    def test_nox_and_percival_learn_and_score(self):
        rows, marks, cm = self.marks()
        m = MT.train_cycle(rows, "v960", cnn_epochs=0, nested=False, image_extra=marks, char_extra=cm)
        nm = m["intelligence"]["families"]["char"]["missed_marks"]
        self.assertEqual(nm["available"], 20); self.assertLessEqual(nm["origin_auc"], 0.75); self.assertTrue(nm["used"])
        self.assertEqual(m["data"]["lumos_missed_marks"]["nox_marks_used"], 20); self.assertEqual(m["data"]["lumos_missed_marks"]["test_marks"], 4)
        self.assertEqual(m["percival_marks"]["inputs"], ["char", "image"])                  # ALBUS is never an input for marks
        self.assertEqual(m["percival_marks"]["development"]["n"], 20)
        self.assertEqual(m["test"]["missed_lesions"]["n"], 4)                                # locked-test marks: evaluation only
        S = MT.score_marks(m, cm[:3]); self.assertEqual(len(S), 3); self.assertTrue(all(s["percival_score"] is not None for s in S))
        json.dumps(m)

    def test_origin_guard_refuses_revealing_marks(self):
        rows, marks, cm = self.marks(reveal=True)
        dev = [r for r in rows if not r["test"]]
        Z, rep = MT.component_oof(dev, k=5, seed=0, cnn_epochs=0, image_kinds=["pixel_logistic"], char_kinds=["logistic"], char_extra=cm)
        nm = rep["char"]["missed_marks"]; self.assertGreater(nm["origin_auc"], 0.75); self.assertFalse(nm["used"]); self.assertIn("origin", nm["decision"])

    def test_nox_never_sees_held_out_marks(self):
        rows, marks, cm = self.marks(); dev = [r for r in rows if not r["test"]]
        seen = []; real = MT.LR.fit_tabular
        def spy(kind, X, y, g, w, cols, seed): seen.append((len(X), set(map(str, g)))); return real(kind, X, y, g, w, cols, seed)
        F = MT.folds(np.array([r["patient"] for r in dev]), 5, 0, np.array([r["y"] for r in dev], float))   # 2026-11-28: stratified folds
        with mock.patch.object(MT.LR, "fit_tabular", side_effect=spy):
            MT.component_oof(dev, k=5, seed=0, cnn_epochs=0, image_kinds=["pixel_logistic"], char_kinds=["logistic"], char_extra=cm, compare_marks=False)
        for (n, pats), (tr, te) in zip(seen[:len(F)], F):
            self.assertFalse(pats & {dev[j]["patient"] for j in te}); self.assertEqual(n, len(tr) + len({dev[j]["patient"] for j in tr}))


class TestPage(unittest.TestCase):
    def test_viewer_parts(self):
        src = open(HTML).read()
        for t in ("function albusLine(", "fetchAlbusMarks(M.study)", "/api/albus_confirm", "rgba(255,159,67,.45)", "const amShow=()=>!!(M&&AM.study===M.study&&!vmode&&!WSM&&!M.blind)"):
            self.assertIn(t, src)


if __name__ == "__main__":
    unittest.main()
