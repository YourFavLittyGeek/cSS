"""2026-11-25 pathway_rules: method requirements, tried / not tried, next method (no FreeSurfer, temporary files only)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))
import pathway_rules as PR                                                    # noqa: E402

ALL_TOOLS = dict(synthseg=True, synthmorph=True, synthmorph_tool=True, synthmorph_model=True, recon=True, coreg=True)
T1_1MM = dict(vox=[1.0, 1.0, 1.0], extent=[256.0, 256.0, 176.0], shape=[256, 256, 176])
SWI_FULL = dict(vox=[0.5, 0.5, 2.0], extent=[230.0, 200.0, 140.0], shape=[460, 400, 70])


def f(**kw):
    d = dict(has_t1=True, has_swi=True, t1=T1_1MM, swi=SWI_FULL, tools=ALL_TOOLS)
    d.update(kw)
    return d


class TestSuitability(unittest.TestCase):
    def test_good_3d_t1_and_whole_brain_swi_allow_everything(self):
        s = PR.suitability(f())
        self.assertTrue(all(ok for ok, _ in s.values()), s)

    def test_no_t1_leaves_only_swi_only(self):
        s = PR.suitability(f(has_t1=False, t1=None))
        self.assertEqual([m for m, (ok, _) in s.items() if ok], ["swi_only"])
        self.assertIn("no usable T1", s["recon"][1])

    def test_thick_or_2d_t1_is_not_for_recon_all(self):
        thick = dict(vox=[0.9, 0.9, 5.0], extent=[230.0, 230.0, 150.0], shape=[256, 256, 30])
        s = PR.suitability(f(t1=thick))
        self.assertFalse(s["recon"][0])
        self.assertIn("1.3 mm", s["recon"][1])
        self.assertTrue(s["synthseg"][0])                                     # SynthSeg is resolution-agnostic
        stack = dict(vox=[1.0, 1.0, 1.2], extent=[200.0, 200.0, 36.0], shape=[200, 200, 30])
        self.assertIn("2-D", PR.suitability(f(t1=stack))["recon"][1])

    def test_partial_slab_swi_rules_out_synthmorph_and_flags_swi_only(self):
        slab = dict(vox=[0.47, 0.47, 1.0], extent=[220.0, 180.0, 64.0], shape=[468, 384, 64])
        s = PR.suitability(f(swi=slab))
        self.assertFalse(s["synthmorph"][0])
        self.assertIn("partial slab", s["synthmorph"][1])
        self.assertTrue(s["swi_only"][0])
        self.assertIn("low confidence", s["swi_only"][1])

    def test_missing_tools_and_models(self):
        self.assertIn("model files", PR.suitability(f(tools=dict(ALL_TOOLS, synthmorph=False, synthmorph_model=False)))["synthmorph"][1])
        self.assertIn("not installed", PR.suitability(f(tools=dict(ALL_TOOLS, synthmorph=False, synthmorph_tool=False)))["synthmorph"][1])
        self.assertIn("not installed", PR.suitability(f(tools=dict(ALL_TOOLS, recon=False)))["recon"][1])


class TestNextMethod(unittest.TestCase):
    def test_states_and_icons(self):
        p = dict(code="X", status="failed", pathway="coreg_masked",
                 tried=[dict(pathway="synthseg", shift="1.8"), dict(pathway="coreg_masked", shift="", reason="mri_coreg crashed")])
        st = PR.statuses(p, PR.suitability(f(has_t1=True, swi=dict(SWI_FULL, extent=[230.0, 200.0, 60.0]))))
        self.assertEqual(st["synthseg"]["state"], "failed")
        self.assertIn("1.8 mm", st["synthseg"]["why"])
        self.assertEqual(st["coreg_masked"]["why"], "mri_coreg crashed")
        self.assertEqual(st["synthmorph"]["state"], "unsuitable")
        self.assertEqual(st["recon"]["state"], "untried")
        done = PR.statuses(dict(status="done", pathway="synthseg", tried=[]), PR.suitability(f()))
        self.assertEqual(done["synthseg"]["state"], "worked")

    def test_order_skips_tried_and_unsuitable(self):
        p = dict(status="failed", pathway="synthseg", tried=[dict(pathway="synthseg", shift="1.6")])
        self.assertEqual(PR.next_method(p, PR.suitability(f()))[0], "coreg_masked")
        p["tried"].append(dict(pathway="coreg_masked", shift="1.7")); p["pathway"] = "coreg_masked"
        self.assertEqual(PR.next_method(p, PR.suitability(f()))[0], "synthmorph")
        slab = dict(vox=[0.5, 0.5, 1.0], extent=[220.0, 180.0, 60.0], shape=[440, 360, 60])
        self.assertEqual(PR.next_method(p, PR.suitability(f(swi=slab)))[0], "recon")      # SynthMorph unsuitable on a slab
        thick = dict(vox=[1.0, 1.0, 4.0], extent=[230.0, 230.0, 150.0], shape=[230, 230, 38])
        self.assertEqual(PR.next_method(p, PR.suitability(f(swi=slab, t1=thick)))[0], "swi_only")

    def test_two_big_misses_mean_the_t1_does_not_match(self):
        """the user's project: shifts 2.3-3.4 mm after SynthSeg - more T1 methods rarely help"""
        p = dict(status="failed", pathway="coreg_masked", tried=[dict(pathway="synthseg", shift="2.34"), dict(pathway="coreg_masked", shift="3.11")])
        nxt, why = PR.next_method(p, PR.suitability(f()))
        self.assertEqual(nxt, "swi_only")
        self.assertIn("another session", why)
        self.assertFalse(PR.t1_mismatch(dict(tried=[dict(pathway="synthseg", shift="2.34"), dict(pathway="coreg_masked", shift="1.7")])))
        self.assertFalse(PR.t1_mismatch(dict(tried=[dict(pathway="synthseg", shift="2.5"), dict(pathway="synthseg", shift="2.6")])))

    def test_nothing_left(self):
        p = dict(status="failed", pathway="swi_only", tried=[dict(pathway=m, shift="1.6") for m in PR.ORDER])
        self.assertEqual(PR.next_method(p, PR.suitability(f()))[0], "")


class TestFactsFromFiles(unittest.TestCase):
    def setUp(self):
        self.B = tempfile.mkdtemp(prefix="pwr_", dir=os.environ["CSS_BASE"])
        self.fs = os.path.join(self.B, "fs")
        for n in ("mri_synthseg", "mri_synthmorph", "recon-all", "bbregister", "mri_coreg"):
            p = os.path.join(self.fs, "bin", n); os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").write("#!/bin/sh\n"); os.chmod(p, 0o755)

    def tearDown(self):
        shutil.rmtree(self.B, ignore_errors=True)

    def nii(self, rel, shape, zooms):
        import nibabel as nib
        p = os.path.join(self.B, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        img = nib.Nifti1Image(np.zeros(shape, np.int16), np.diag(list(zooms) + [1]))
        img.header.set_zooms(zooms); nib.save(img, p)

    def test_the_largest_volume_is_used_not_a_localizer(self):
        self.nii("raw/S8/SWI/400_SWAN_i00001.nii.gz", (64, 64, 1), (0.47, 0.47, 0.47))           # Study-026 had this split-off slice
        self.nii("raw/S8/SWI/400_SWAN_i00002.nii.gz", (64, 64, 52), (0.39, 0.39, 3.0))
        g = PR._nifti_geom(os.path.join(self.B, "raw", "S8", "SWI"))
        self.assertEqual(g["shape"], [64, 64, 52])
        self.assertAlmostEqual(g["extent"][2], 156.0, places=3)

    def test_headers_and_tools_are_read(self):
        self.nii("raw/S9/T1/3_T1.nii.gz", (64, 64, 20), (1.0, 1.0, 5.0))
        self.nii("raw/S9/SWI/15_SWI.nii.gz", (100, 100, 30), (0.5, 0.5, 2.0))
        p = dict(code="S9", status="failed", pathway="synthseg", series=dict(SWI="x", T1="y"), tried=[dict(pathway="synthseg", shift="1.9")])
        s = PR.summary(self.B, p, self.fs)
        m = {x["key"]: x for x in s["methods"]}
        self.assertEqual(m["recon"]["state"], "unsuitable")                     # 5 mm T1
        self.assertEqual(m["synthmorph"]["state"], "unsuitable")                # no model file + 60 mm slab
        self.assertIn("model files", m["synthmorph"]["why"])
        os.makedirs(os.path.join(self.fs, "models"), exist_ok=True)
        open(os.path.join(self.fs, "models", "synthmorph.rigid.1.h5"), "w").close()
        m = {x["key"]: x for x in PR.summary(self.B, p, self.fs)["methods"]}
        self.assertIn("partial slab", m["synthmorph"]["why"])
        self.assertEqual(s["next"], "coreg_masked")
        self.assertEqual(m["synthseg"]["icon"], "✗")


if __name__ == "__main__":
    unittest.main()
