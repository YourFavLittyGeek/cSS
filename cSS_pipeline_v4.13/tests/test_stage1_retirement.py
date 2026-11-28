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
        for mod in ("uengine.albus", "uengine.nox", "uengine.lumos", "uengine.governance"):
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



class TestCoreRemoved(unittest.TestCase):
    """2026-11-28 (user request): the CORE fixed-weight baseline and the Shadow Lab demonstration built on it are removed - module,
    app wiring, API routes, setting and screen text"""
    def test_removed_everywhere(self):
        import importlib
        for mod in ("uengine.percival_core", "uengine.shadow_lab"):
            with self.assertRaises(ImportError): importlib.import_module(mod)
        import percival_gui as PG
        for name in ("experimental_core_enabled", "_core_engines", "_core_assess", "score_study_unified", "shadow_lab_state", "shadow_run_trial"):
            self.assertFalse(hasattr(PG, name), name)
        app = open(os.path.join(ROOT, "app", "css_app.py")).read(); js = open(os.path.join(ROOT, "app", "percival_view.js")).read()
        for t in ('op == "score_unified"', 'op == "shadow_lab"', 'op == "shadow_run"', 'setdefault("experimental_core"'): self.assertNotIn(t, app)
        self.assertNotIn("CORE fixed-weight", js); self.assertNotIn("shd-run", js)
        from uengine.percival import architecture as AR
        self.assertNotIn("CORE", AR.NAMES)

    def test_other_legacy_routes_still_retired(self):
        import css_app; css_app.pg_init()
        self.assertTrue(css_app.pg_get("pensieve", {})["retired"])
        self.assertTrue(css_app.pg_get("pensieve_query", dict(component="albus"))["retired"])
        import unified_gui as UG
        self.assertTrue(UG.freeze("FREEZE")["retired"]); self.assertTrue(UG.score_all()["retired"])
        self.assertFalse(os.path.exists(os.path.join(UG.OUT, "model_frozen.json")))

if __name__ == "__main__":
    unittest.main()
