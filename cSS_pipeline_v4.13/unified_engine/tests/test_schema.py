"""feature schema: complete coverage of the detector columns, roles, initial feature set, consumption maps verified against the source"""
import re, unittest
import _common  # noqa: F401
from uengine import feature_schema as fs, provenance as pv, math_component as mc


class TestSchema(unittest.TestCase):
    def test_every_detector_column_classified_exactly_once(self):
        cols = pv.detector_columns()
        self.assertEqual(sorted(cols), sorted(fs.SCHEMA), msg=f"unclassified {set(cols) - set(fs.SCHEMA)}, extra {set(fs.SCHEMA) - set(cols)}")
        self.assertTrue(all(c.role in fs.ROLES for c in fs.SCHEMA.values()))

    def test_role_counts_recorded(self):
        counts = {r: len(fs.columns_by_role(r)) for r in fs.ROLES}
        self.assertEqual(sum(counts.values()), 157)
        # the inventory number reported in FEATURE_SCHEMA.md (measured, i.e. eligible characteristics)
        self.assertEqual(counts["measured"], len(fs.measured()))
        self.assertGreaterEqual(counts["measured"], 60)
        print("\n   role counts:", counts)

    def test_initial_feature_set(self):
        self.assertLessEqual(len(fs.INITIAL_COLUMNS), fs.MAX_INPUT_COLUMNS)
        for c in fs.INITIAL_FEATURES:
            base = fs.TRANSFORMS[c][0] if c in fs.TRANSFORMS else c
            self.assertEqual(fs.SCHEMA[base].role, "measured", c)
            self.assertFalse(fs.is_forbidden_predictor(c), c)
            self.assertNotIn(base, fs.UNSUITABLE_INITIAL, c)
        for ind, src in fs.INITIAL_INDICATORS.items():
            self.assertEqual(fs.SCHEMA[src].missing, "structural")

    def test_forbidden_predictors(self):
        for c in ("cand_id", "vox_i", "accept", "score", "score_v4", "css_evidence", "confidence_pct", "conf_guard", "review_tier",
                  "rule_version", "vein_tree_mm", "y", "patient_key", "exam_id", "score_model", "struct_cls", "mimic_score", "qc_status"):
            self.assertTrue(fs.is_forbidden_predictor(c), c)
        for c in ("darkness_z", "pial_dist_mm", "tram_frac_missing", "log_volume_mm3"):
            self.assertFalse(fs.is_forbidden_predictor(c), c)

    def test_rule_use_matches_exclusion_source(self):
        ref = r"""r\[["'](\w+)["']\]"""
        lines = mc.EXCLUSION_SRC.splitlines()
        decide = set(); every = set(re.findall(ref, mc.EXCLUSION_SRC))
        for i, l in enumerate(lines):                     # decision = referenced in an 'if' condition (incl. its continuation line)
            s = l.strip()
            if s.startswith("if ") or (i and lines[i - 1].rstrip().endswith("\\")) or s.startswith("and ") or s.startswith("tub_, tram_"):
                decide |= set(re.findall(ref, l))
        declared = {c for cols in fs.RULE_USE.values() for c in cols} | {"_band"}
        reason = {c for cols in fs.RULE_REASON_ONLY.values() for c in cols}
        self.assertEqual(decide, declared, f"decision inputs in source not declared: {decide - declared}; declared but not deciding: {declared - decide}")
        self.assertEqual(every - decide, reason - decide, "reason-only fields")
        self.assertNotIn("confidence_pct", every)               # E30 is not in exclusion_v4 (it is in exclusion(): learned)
        self.assertIn('r["confidence_pct"] < float(CONF_MODEL', pv.function_source("exclusion"))

    def test_score_v4_inputs(self):
        # every variable the verbatim block reads maps to exactly the declared columns
        self.assertEqual(set(fs.MATH_USE["score_v4"]), {"darkness_z", "pial_dist_mm", "tube_ratio", "surface_alignment", "tram_frac",
                                                       "artifact_zone", "midline_zone", "long_structure", "infratentorial"})
        for v in ("depth", "pdist", "tub", "aln", "tram", "artz", "midz", "longs", "infra"):
            self.assertRegex(mc.SCORE_V4_SRC, rf"\b{v}\b")

    def test_legacy_model_inputs_classified(self):
        cc = pv.load_legacy("css_confidence"); tr = pv.load_legacy("train_ranker")
        self.assertEqual(len(cc.FEATURES), 30)
        derived = {"is_ball": "struct_cls", "is_tube": "struct_cls", "is_ribbon": "struct_cls", "width_over_thick": "struct_s2_mm", "log_volume": "volume_mm3"}
        roles = {f: fs.SCHEMA[derived.get(f, f)].role for f in cc.FEATURES}
        self.assertEqual(sorted(f for f, r in roles.items() if r != "measured"), ["cmb_like", "is_ball", "is_ribbon", "is_tube"])
        rk = {f: (fs.SCHEMA[f].role if f in fs.SCHEMA else "other-file") for f in tr.FEATURES}
        self.assertEqual(rk["mimic_score"], "rule_flag")          # finding: the ranker uses a rule-derived score as a feature
        self.assertEqual(len(tr.FEATURES), 52)

    def test_overlap_matrix(self):
        o = fs.overlap_matrix()
        self.assertIn("score_v4", o["darkness_z"]); self.assertIn("E9", o["edge_contrast"]); self.assertIn("E18", o["edge_contrast"])
        self.assertEqual(o["local_cont_max_mm"], ["review_priority"]); self.assertIn("G1_volume", o["log_volume_mm3"])


if __name__ == "__main__":
    unittest.main()
