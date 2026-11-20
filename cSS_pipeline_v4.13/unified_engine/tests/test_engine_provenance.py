"""the engine executes the repository's own production code: pinned sources, pinned verbatim blocks, rule constants, column contract"""
import json, os, unittest
import _common
from uengine import provenance as pv, math_component as mc

with open(os.path.join(_common.ENGINE, "tests", "pinned_blocks.json")) as _f: PINNED = json.load(_f)


class TestEngineProvenance(unittest.TestCase):
    def test_pinned_sources_unchanged(self):
        self.assertEqual(pv.verify_sources(), [])
        self.assertTrue(pv.detector_sha_prefix_ok())

    def test_verbatim_blocks_pinned(self):
        for k, src in (("score_v4", mc.SCORE_V4_SRC), ("evidence", mc.EVIDENCE_SRC), ("tier", mc.TIER_SRC), ("exclusion_v4", mc.EXCLUSION_SRC)):
            self.assertEqual(pv.sha256_text(src)[:12], PINNED[k], k)

    def test_rule_constants_and_columns(self):
        C = mc.CONSTANTS
        for k, v in dict(E15_SKULL=0.70, E18_EDGE=1.5, E24_FRAC=0.2, ZONE2_FRAC=0.0, SYLV_FRAC=0.2, VES_EXCL_WM_MM=4.0).items():
            self.assertAlmostEqual(float(C[k]), v, msg=k)
        cols = pv.detector_columns(); self.assertEqual(len(cols), 157); self.assertEqual(cols[-1], "single_slice")

    def test_engine_is_inside_the_repository(self):
        self.assertTrue(os.path.samefile(pv.DETECTOR, os.path.join(pv.ROOT, "scripts", "detect_css.py")))
        self.assertFalse(os.environ["CSS_BASE"].startswith(os.path.expanduser("~/css_project")))


if __name__ == "__main__":
    unittest.main()
