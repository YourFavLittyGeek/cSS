"""Stage 1 (retire redundant layers) - tests/run_isolated_suite.py only. Every retired item is retired reversibly and verifiably:
governance promotion refuses and writes nothing; the legacy engines never touch the global legacy PENSIEVE or the external Vault by default;
the Shadow Lab trials never read labels; CORE uses real measurements (missing -> unavailable, no invented defaults); the legacy PENSIEVE
routes and the in-app uScore freeze / score-all are retired; frozen app bundles are gone from the tree; the register lists every item."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path: sys.path.insert(0, p)


class _NoGlobal:
    """patch uengine.pensieve.get_pensieve / uengine.vault.get_vault so that any default use fails the test"""
    def __enter__(self):
        import uengine.pensieve as PE, uengine.vault as VA
        self.mods = [(PE, "get_pensieve", PE.get_pensieve), (VA, "get_vault", VA.get_vault)]
        def boom(*a, **k): raise AssertionError("global legacy PENSIEVE / external Vault used by a retired default path")
        for m, n, _ in self.mods: setattr(m, n, boom)
        for mod in ("uengine.albus", "uengine.nox", "uengine.lumos", "uengine.percival_core", "uengine.shadow_lab", "uengine.governance"):
            M = sys.modules.get(mod)
            if M is not None:
                for n in ("get_pensieve", "get_vault"):
                    if hasattr(M, n): self.mods.append((M, n, getattr(M, n))); setattr(M, n, boom)
        return self

    def __exit__(self, *a):
        for m, n, f in self.mods: setattr(m, n, f)


class TestRetiredLayers(unittest.TestCase):
    def test_governance_promotion_refuses_and_writes_nothing(self):
        from uengine.governance import PercivalGovernance
        from uengine.contracts import GovernanceProposal
        with _NoGlobal():
            gov = PercivalGovernance()
            p = GovernanceProposal(proposal_id="p1", experiment_id="e1", target_component="ALBUS", hypothesis="h", rationale="r",
                                   validation_results=dict(baseline=dict(sensitivity=0.8, false_positives=3.0, auc=0.8),
                                                           experimental=dict(sensitivity=0.9, false_positives=2.0, auc=0.9)),
                                   leakage_audit_passed=True, sensitivity_loss=0.0, false_positive_reduction=1.0)
            ok, msg = gov.promote_proposal(p, "Dr X", "because", override=True)
            self.assertFalse(ok); self.assertIn("RETIRED", msg); self.assertNotEqual(p.verdict, "approved")
            self.assertFalse(gov.rollback("ALBUS")[0])
            self.assertEqual(gov.get_audit_trail()[-1]["status"], "refused_retired")

    def test_legacy_engines_never_use_global_memory_or_the_vault_by_default(self):
        with _NoGlobal():
            from uengine.albus import AlbusDiscoveryEngine
            from uengine.nox import NoxCharacteristicsEngine
            from uengine.lumos import LumosImageIntelligence
            from uengine.percival_core import PercivalCoreIntelligence
            from uengine.shadow_lab import ShadowMLLaboratory
            a = AlbusDiscoveryEngine(); n = NoxCharacteristicsEngine(); l = LumosImageIntelligence(); c = PercivalCoreIntelligence(); s = ShadowMLLaboratory()
            self.assertFalse(l.trained)                                     # no Vault loader -> untrained, not a silent checkpoint
            for o in (a, n, l, c, s): self.assertTrue(getattr(o.pensieve, "retired", False))
            for o in (l, c, s): self.assertFalse(o.vault.is_connected())
            raw = dict(pial_distance=0.5, darkness_z=-3.0, tube_ratio=1.2, cortex_frac=0.7, tram_frac=0.1)
            ca = a.discover_candidate("S1", 1, "L", (0, 0, 0), (0, 0, 0), 0, 0.0, (0,) * 6, raw)
            asmt = c.evaluate_candidate(ca, l.analyze_patch("S1", 1, None), n.measure_candidate("S1", 1, raw))
            self.assertIsNotNone(asmt)

    def test_shadow_lab_trials_are_synthetic_only(self):
        from uengine.shadow_lab import ShadowMLLaboratory
        class Rich:                                                          # a memory full of (unverified) development rows
            retired = False
            def get_training_dataset(self, part): return [dict(call="cSS" if i % 2 else "Unsure", nox_measurements="{}", patient_pseudo_id=i) for i in range(40)]
            def __getattr__(self, n): return lambda *a, **k: None
        lab = ShadowMLLaboratory(pensieve=Rich(), vault=__import__("uengine.legacy_guard", fromlist=["NullVault"]).NullVault())
        lab._get_benchmark_cohort()
        self.assertTrue(lab.last_cohort.startswith("SYNTHETIC"))

    def test_core_uses_real_measurements_and_reports_missing(self):
        import percival_gui as PG
        r_ok = dict(cand_id=1, hemi="L", char=dict(pial_dist_mm=0.4, darkness_z=-3.1, tube_ratio=1.1, cortex_frac=0.8, tram_frac=0.2))
        raw, miss = PG._core_inputs(r_ok); self.assertEqual(miss, []); self.assertEqual(raw["darkness_z"], -3.1)
        r_miss = dict(cand_id=2, hemi="L", char=dict(pial_dist_mm=0.4, darkness_z=None))
        raw, miss = PG._core_inputs(r_miss); self.assertIsNone(raw); self.assertIn("tube_ratio", miss)
        import css_app; css_app.pg_init()                                    # initialises percival_gui's context on the isolated project
        with _NoGlobal():
            eng = PG._core_engines()
            out = PG._core_assess("S1", r_miss, eng)
            self.assertIsNone(out["score"]); self.assertEqual(out["status"], "unavailable"); self.assertIn("missing NOX", out["reason"])
            out = PG._core_assess("S1", r_ok, eng)
            self.assertIn("EXPERIMENTAL", out["label"]); self.assertEqual(out["inputs"]["darkness_z"], -3.1)

    def test_legacy_routes_and_uscore_app_actions_are_retired(self):
        import css_app; css_app.pg_init()
        self.assertTrue(css_app.pg_get("pensieve", {})["retired"])
        self.assertTrue(css_app.pg_get("pensieve_query", dict(component="albus"))["retired"])
        st = css_app.pg_get("shadow_lab", {}); self.assertTrue(st["retired"]); self.assertIn("SYNTHETIC DEMONSTRATION", st["label"])
        import unified_gui as UG
        self.assertTrue(UG.freeze("FREEZE")["retired"]); self.assertTrue(UG.score_all()["retired"])
        self.assertFalse(os.path.exists(os.path.join(UG.OUT, "model_frozen.json")))

    def test_frozen_bundles_removed_and_register_complete(self):
        tracked = subprocess.run(["git", "ls-files", "app/mac", "docs/gui_v514"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
        if tracked:                                                          # source checkout (a release zip has no .git)
            self.assertFalse([f for f in tracked if "cSS Pipeline.app/" in f or "/dist/" in f])
        self.assertIn("OBSOLETE", open(os.path.join(ROOT, "app", "mac", "START_HERE.txt")).read())
        from uengine.legacy_guard import RETIRED
        self.assertEqual(len(RETIRED), 7)
        reg = os.path.join(os.path.dirname(ROOT), "docs", "engineering", "DEPRECATIONS.md")
        if os.path.exists(reg):
            rows = [l for l in open(reg) if l.startswith("| ") and l[2:3].isdigit()]
            self.assertEqual(len(rows), 7)


if __name__ == "__main__":
    unittest.main()
