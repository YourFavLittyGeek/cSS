"""test_shadow_and_governance.py - Verification of SHADOW ML Lab and PERCIVAL GOVERNANCE"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import sys
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "unified_engine"))

from uengine.vault import PercivalDataVault
from uengine.pensieve import PensieveCoreMemory
from uengine.shadow_lab import ShadowMLLaboratory
from uengine.governance import PercivalGovernance

class TestShadowAndGovernance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="shd_gov_test_")
        self.vault = PercivalDataVault.create_vault(self.temp_dir, name="VAULT_SHD")
        self.pensieve = PensieveCoreMemory(self.vault)
        self.shadow = ShadowMLLaboratory(pensieve=self.pensieve, vault=self.vault)
        self.governance = PercivalGovernance(pensieve=self.pensieve, vault=self.vault)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_shadow_experiment_and_proposal(self):
        # 1. Formulate ALBUS experiment
        exp = self.shadow.formulate_hypothesis(
            target_component="ALBUS",
            hypothesis_text="Adaptive subpial weighting recovers missed lesions without increasing false positives.",
            experimental_config={"formula": "formula_adaptive_subpial", "threshold": 0.45}
        )
        self.assertEqual(exp.status, "queued")

        # 2. Run experiment
        ok, proposal = self.shadow.run_experiment(exp)
        self.assertTrue(ok)
        self.assertEqual(exp.status, "completed")
        self.assertIsNotNone(proposal)
        self.assertTrue(os.path.exists(exp.data_vault_artifact_path))

        # 3. Governance Evaluation
        evaluation = self.governance.evaluate_proposal(proposal)
        self.assertFalse(evaluation["all_passed"])                            # Phase 3D: no leakage audit ran -> never auto-approved
        self.assertNotIn("Approved", evaluation["recommendation"])

        # 4. Governance Promotion
        promoted, msg = self.governance.promote_proposal(
            proposal=proposal,
            approver_id="Chief_Scientist",
            reason="Verified improvement in sensitivity (+0.02) and false positive reduction (-0.8/scan).", override=True   # explicit override
        )
        self.assertTrue(promoted)
        self.assertEqual(proposal.verdict, "approved")
        self.assertTrue(proposal.promoted_version.startswith("albus-v"))

        # 5. Rollback verification
        rb_ok, rb_msg = self.governance.rollback("ALBUS")
        self.assertTrue(rb_ok)

    def test_governance_rejection_on_sensitivity_loss(self):
        # Test that governance rejects an experiment that drops sensitivity
        from uengine.contracts import GovernanceProposal
        bad_proposal = GovernanceProposal(
            proposal_id="prop_bad",
            experiment_id="exp_bad",
            target_component="ALBUS",
            hypothesis="Aggressive vessel filter",
            rationale="Reduces false positives drastically but loses true cSS lesions",
            validation_results={
                "baseline": {"auc": 0.85, "sensitivity": 0.95, "false_positives": 3.0},
                "experimental": {"auc": 0.87, "sensitivity": 0.88, "false_positives": 0.5} # Lost 7% sensitivity!
            },
            leakage_audit_passed=True,
            sensitivity_loss=0.07,
            false_positive_reduction=2.5
        )

        evaluation = self.governance.evaluate_proposal(bad_proposal)
        self.assertFalse(evaluation["all_passed"])
        self.assertIn("Rejected", evaluation["recommendation"])

        ok, msg = self.governance.promote_proposal(bad_proposal, "User", "Should fail")
        self.assertFalse(ok)
        self.assertEqual(bad_proposal.verdict, "rejected")

if __name__ == "__main__":
    unittest.main()
