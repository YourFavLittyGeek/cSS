"""2026-11-25 LUMOS second look (user decision: build it, inactive until LUMOS has enough marks; LUMOS checks the marks; rejected
suggestions teach LUMOS 'not cSS').
- activation gate: >= 50 marks learned, >= 10 patients, >= 70 % of held-out patients' marks recognised, an image model; else inactive
  with the reasons;
- LUMOS checks the marks: every cycle the fold models score the marks of the patients they were not trained on;
- spots: dark, in the cortical band, never on / next to a detector object; suggestions above the threshold, best first, at most 10;
- the reviewer: suggestions refused in a blind read (route table), reject -> own file (validated), accept -> missed mark with context
  'lumos_suggestion'; decided suggestions are reported back; marks with a plane NAME draw and 'go to' (regression of 01e95bc).
- rejected suggestions of experts are 'not cSS' (y = 0) image examples; never from a test patient.
Synthetic data only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
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

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "scripts"), os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)
from uengine.imaging import synthetic_images as SI                   # noqa: E402
from uengine.percival import meta as MT, second_look as SLK          # noqa: E402
from uengine.percival.cnn import IN_SHAPE                            # noqa: E402
from test_lumos_missed_marks import rows_and_marks                   # noqa: E402
HTML = os.path.join(ROOT, "scripts", "review_web.html"); NODE = shutil.which("node")


def model_with(n=60, pats=12, recall=0.8, image=True):
    return dict(version="v009", components=dict(image={"w": 1} if image else None),
                data=dict(lumos_missed_marks=dict(used=n, patients=pats)),
                intelligence=dict(families=dict(image=dict(missed_marks=dict(heldout_check=dict(n=n, recognised=int(n * (recall or 0)), recall=recall))))))


class TestGate(unittest.TestCase):
    def test_inactive_until_enough(self):
        self.assertFalse(SLK.status(None)["active"])
        st = SLK.status(model_with(10, 3, None)); self.assertFalse(st["active"])
        self.assertEqual(len(st["reasons"]), 3); self.assertIn("10 expert-marked", st["reasons"][0])
        self.assertIn("recognises 50 %", " ".join(SLK.status(model_with(60, 12, 0.5))["reasons"]))
        self.assertTrue(SLK.status(model_with())["active"])
        self.assertFalse(SLK.status(model_with(), {"lumos_second_look": False})["active"])        # can be switched off
        self.assertFalse(SLK.status(model_with(image=False))["active"])

    def test_trained_model_records_its_gate_and_the_heldout_check(self):
        rows, marks = rows_and_marks()
        m = MT.train_cycle(rows, "v910", cnn_epochs=0, nested=False, image_extra=marks)
        hc = m["intelligence"]["families"]["image"]["missed_marks"]["heldout_check"]
        self.assertEqual(hc["n"], 20)                           # every development mark checked once, by a fold that never saw its patient
        self.assertGreater(hc["recall"], 0.5)                   # the synthetic marks carry the cSS signal
        self.assertFalse(m["second_look"]["ready"]); self.assertIn("50 needed", " ".join(m["second_look"]["reasons"]))
        self.assertEqual(m["modules"]["LUMOS"]["missed_marks_check"]["n"], 20)

    def test_rejected_suggestions_are_not_css_examples(self):
        rows, marks = rows_and_marks(); rej = [dict(m, cand_id="lumos_reject_spot_1", y=0, maps=np.zeros(IN_SHAPE, np.float32)) for m in marks[:6]]
        m = MT.train_cycle(rows, "v911", cnn_epochs=0, nested=False, image_extra=marks + rej)
        L = m["data"]["lumos_missed_marks"]
        if L["used"]: self.assertEqual(L["rejected_suggestions_used"], 6)
        M, y, g, n = MT._with_marks(np.zeros((1,) + IN_SHAPE, np.float32), np.array([1.0]), np.array(["P00"]), rej, {"P00"})
        self.assertEqual(list(y), [1.0, 0.0])


class TestSpots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.B = tempfile.mkdtemp(prefix="second_look_"); SI.write_study(cls.B, "SYN01")

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.B, ignore_errors=True)

    def test_spots_avoid_detector_objects_and_scan_ranks(self):
        sp = SLK.find_spots(self.B, "SYN01")
        lab = np.asarray(nib.load(os.path.join(self.B, "review", "SYN01_candidates.nii.gz")).dataobj) > 0
        for _, m, info in sp:
            self.assertFalse((m & lab).any()); self.assertTrue(SLK.MIN_VOX <= info["n_vox"] <= SLK.MAX_VOX)
        class Net:
            def logit_tta(self, M): v = np.linspace(3, -3, len(M)); return v, np.zeros(len(M))
        r = SLK.scan(self.B, "SYN01", Net())
        self.assertLessEqual(len(r["suggestions"]), SLK.MAX_SUGGESTIONS)
        ps = [s["p"] for s in r["suggestions"]]; self.assertEqual(ps, sorted(ps, reverse=True)); self.assertTrue(all(p >= 0.5 for p in ps))
        self.assertEqual(set(r["maps"]), {s["key"] for s in r["suggestions"]})
        can = nib.as_closest_canonical(nib.load(os.path.join(self.B, "data", "SYN01_swi.nii")))
        for s in r["suggestions"]: self.assertTrue(all(0 <= c < n for c, n in zip(s["can"], can.shape)))
        class No:
            def logit_tta(self, M): return np.full(len(M), -5.0), np.zeros(len(M))
        self.assertEqual(SLK.scan(self.B, "SYN01", No())["suggestions"], [])


class TestReviewer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import review_web as RW
        cls.RW = RW

    def test_routes_refused_in_a_blind_read(self):
        self.assertEqual(self.RW.ROUTES[("GET", "/api/second_look")], "refused")
        self.assertEqual(self.RW.ROUTES[("POST", "/api/lumos_reject")], "refused")
        src = open(os.path.join(ROOT, "scripts", "review_web.py")).read()
        self.assertIn('"lumos_suggestion" if d.get("source") == "lumos_suggestion" and not blind', src)

    def test_reject_file(self):
        RW = self.RW; sid = "SLK01"
        r = RW.lumos_reject(sid, "Dr Test", dict(key="spot_3", model="v009", p=0.81, vox=[1, 2, 3]), read_phase="open", ai_visible=True)
        r = RW.lumos_reject(sid, "Dr Test", dict(key="spot_3", model="v009", p=0.81, vox=[1, 2, 3]))
        self.assertEqual(len(r), 1)                                       # one row per suggestion
        with self.assertRaises(RW.RB.BlindError): RW.lumos_reject(sid, "Dr Test", dict(key="../x", model="v"))
        import percival_gui as PG
        with mock.patch.object(PG, "B", return_value=RW.B):
            mp = os.path.join(RW.B, "review", f"{sid}_missed.csv")
            with open(mp, "w") as f: f.write("missed_id,comment\n1,LUMOS suggestion spot_5 (v009) · 77 %\n2,LUMOS suggestion spot_6 (v001) · 70 %\n")
            self.assertEqual(PG._sl_decided(sid, "v009"), {"spot_3": "rejected", "spot_5": "accepted"})
            os.remove(mp)

    def test_rejects_become_examples_only_from_experts_and_never_test(self):
        import percival_gui as PG
        RW = self.RW; sid = "SLK02"
        RW.lumos_reject(sid, "Dr Expert", dict(key="spot_1", model="v009", p=0.9, vox=[1, 1, 1]))
        RW.lumos_reject(sid, "Trainee", dict(key="spot_2", model="v009", p=0.9, vox=[1, 1, 1]))
        d = tempfile.mkdtemp(); zp = os.path.join(d, f"{sid}.npz"); np.savez(zp, spot_1=np.ones(IN_SHAPE, np.float32), spot_2=np.ones(IN_SHAPE, np.float32))
        class Roles:
            @staticmethod
            def current(b): return {}
            @staticmethod
            def role_of(b, n, t=None): return "expert" if n == "Dr Expert" else "trainee"
        class Led: RR = Roles
        with mock.patch.object(PG, "B", return_value=RW.B), mock.patch.object(PG, "P", side_effect=lambda *a: os.path.join(d, a[-1])), \
             mock.patch.object(PG, "_ledger_mod", return_value=Led), mock.patch.object(PG, "IDS", return_value=mock.Mock(patient=lambda s: "PX")):
            ex = PG._lumos_rejects(sid, False)
            self.assertEqual([(e["cand_id"], e["y"]) for e in ex], [("lumos_reject_spot_1", 0)])
            self.assertEqual(PG._lumos_rejects(sid, True), [])


@unittest.skipIf(NODE is None, "node is not installed")
class TestPage(unittest.TestCase):
    def test_plane_names_and_indices(self):
        src = open(HTML).read(); i = src.index("const planeIdx="); line = src[i:src.index("\n", i)].split("   //")[0]
        code = 'const PLN=["Axial","Coronal","Sagittal"];' + line + ';process.stdout.write(JSON.stringify(["axial","coronal","sagittal","0","2","",null,"x"].map(planeIdx)))'
        r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(json.loads(r.stdout), [0, 1, 2, 0, 2, -1, -1, -1])
        self.assertIn("m.pi===p.plane", src); self.assertNotIn("+m.plane", src)
        self.assertIn('source:"lumos_suggestion"', src); self.assertIn("fetchSecondLook(M.study)", src)

    def test_save_button_and_edge_clip(self):
        """2026-11-25 user report: Save did not save (onclick=saveDraft took the click event for the drawing); a pen stroke past the image
        edge made the server refuse the whole mark (browser-tested on the synthetic demo: pen + Save, rectangle, past-edge pen, Enter,
        reopen shows the drawings)"""
        src = open(HTML).read()
        self.assertNotIn('$("#dSave").onclick=saveDraft', src); self.assertIn('$("#dSave").onclick=()=>{', src)
        self.assertIn("strokes:d.strokes.map(st=>st.map(clip))", src)


if __name__ == "__main__":
    unittest.main()
