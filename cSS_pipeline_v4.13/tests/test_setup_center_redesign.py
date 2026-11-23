"""Comprehensive unit and integration test suite for PERCIVAL Setup Center,
First-Launch Lifecycle, and System Configuration Redesign.

Mission ID: PERCIVAL-SETUP-REDESIGN-2026
"""

import os
import sys
import json
import shutil
import tempfile
import unittest

from uengine.setup.models import (
    SetupStateEnum,
    SetupMode,
    InstallationCandidate,
    ReadinessCapability
)
from uengine.setup.setup_state_manager import (
    SetupStateManager,
    CURRENT_APP_VERSION
)
from uengine.setup.validators import (
    validate_python,
    validate_pipeline,
    validate_freesurfer,
    validate_license,
    validate_mri_tool,
    validate_workspace,
    validate_vault,
    validate_pensieve
)
from uengine.setup.installation_discovery import InstallationDiscoveryService
from uengine.setup.readiness_service import SystemReadinessService
from uengine.setup.diagnostic_export import DiagnosticExportService


class TestSetupCenterRedesign(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="percival_setup_test_")
        self.workspace = os.path.join(self.tmp_dir, "Percival_project")
        os.makedirs(self.workspace, exist_ok=True)
        self.state_mgr = SetupStateManager(self.workspace)
        self.discovery_svc = InstallationDiscoveryService(self.workspace)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_first_launch_state_and_dashboard_blocking(self):
        """Verify that a fresh installation starts in FIRST_LAUNCH and blocks dashboard access."""
        lm = self.state_mgr.detect_launch_mode(CURRENT_APP_VERSION)
        self.assertEqual(lm["launch_type"], "first_launch")
        self.assertEqual(lm["state"], SetupStateEnum.FIRST_LAUNCH.value)
        self.assertFalse(lm["allow_dashboard"])
        self.assertFalse(self.state_mgr.is_dashboard_allowed())

    def test_setup_step_navigation_and_resume(self):
        """Verify that stepping through the wizard preserves partial config and resumes on restart."""
        # Advance to step 3 with partial config
        self.state_mgr.set_step(3, {"freesurfer_home": "/Applications/freesurfer/8.2.0"})
        st = self.state_mgr.get_state()
        self.assertEqual(st["current_step"], 3)
        self.assertEqual(st["state"], SetupStateEnum.SETUP_IN_PROGRESS.value)
        self.assertEqual(st["pending_config"].get("freesurfer_home"), "/Applications/freesurfer/8.2.0")

        # Simulate application close and restart: create a new manager on same workspace
        restarted_mgr = SetupStateManager(self.workspace)
        lm = restarted_mgr.detect_launch_mode(CURRENT_APP_VERSION)
        self.assertEqual(lm["launch_type"], "setup_resume")
        self.assertEqual(lm["resume_step"], 3)
        self.assertFalse(lm["allow_dashboard"])
        self.assertEqual(restarted_mgr.get_state()["pending_config"].get("freesurfer_home"), "/Applications/freesurfer/8.2.0")

    def test_setup_completion_and_subsequent_dashboard_access(self):
        """Verify that completing setup persists state and opens dashboard on subsequent launches."""
        readiness_summary = {"ready": True, "blockers_count": 0, "warnings_count": 0}
        self.state_mgr.mark_completed(readiness_summary)

        st = self.state_mgr.get_state()
        self.assertEqual(st["state"], SetupStateEnum.SETUP_COMPLETED.value)
        self.assertTrue(st["completed"])
        self.assertTrue(self.state_mgr.is_dashboard_allowed())

        # Test subsequent launch
        restarted_mgr = SetupStateManager(self.workspace)
        lm = restarted_mgr.detect_launch_mode(CURRENT_APP_VERSION)
        self.assertEqual(lm["launch_type"], "standard_launch")
        self.assertTrue(lm["allow_dashboard"])
        self.assertEqual(lm["state"], SetupStateEnum.SETUP_COMPLETED.value)

    def test_application_update_does_not_reset_setup(self):
        """Verify that updating the application version preserves configuration and setup status."""
        self.state_mgr.update_validated_config({
            "freesurfer_home": "/Applications/freesurfer/8.2.0",
            "workspace_dir": self.workspace
        })
        self.state_mgr.mark_completed({"ready": True})

        # Simulate update to a newer application version
        restarted_mgr = SetupStateManager(self.workspace)
        lm = restarted_mgr.detect_launch_mode(app_version="v5.27-Next-Gen-Update")

        self.assertEqual(lm["launch_type"], "application_update")
        self.assertTrue(lm["allow_dashboard"])
        # Verify validated config survived
        cfg = restarted_mgr.get_state()["validated_config"]
        self.assertEqual(cfg.get("freesurfer_home"), "/Applications/freesurfer/8.2.0")
        self.assertIn("v5.27", lm["notice"])

    def test_revert_configuration_rollback(self):
        """Verify that configuration changes can be safely reverted to previous working state."""
        self.state_mgr.update_validated_config({"test_key": "initial_value"})
        self.state_mgr.update_validated_config({"test_key": "mutated_value"})

        st = self.state_mgr.get_state()
        self.assertEqual(st["validated_config"]["test_key"], "mutated_value")

        ok, msg = self.state_mgr.revert_to_previous_config()
        self.assertTrue(ok)
        st_after = self.state_mgr.get_state()
        self.assertEqual(st_after["validated_config"]["test_key"], "initial_value")

    def test_validate_python(self):
        """Test Python validator on current active runtime."""
        val = validate_python(sys.executable)
        self.assertTrue(val["ok"], val.get("error"))
        self.assertGreaterEqual(val["version_info"][1], 10)
        self.assertEqual(len(val["missing_packages"]), 0)

    def test_validate_workspace(self):
        """Test internal workspace validator for write access and headroom reporting."""
        val = validate_workspace(self.workspace)
        self.assertTrue(val["ok"])
        self.assertTrue(val["writable"])
        self.assertGreater(val["free_gb"], 0.0)

    def test_validate_license_structure(self):
        """Test FreeSurfer license structure validator without leaking contents."""
        lic_file = os.path.join(self.tmp_dir, "test_license.txt")
        # Write valid structure
        with open(lic_file, "w") as f:
            f.write("user@hospital.org\n1234567890\nABCD-EFGH\n*XYZ123*\n")

        val = validate_license(lic_file)
        self.assertTrue(val["ok"])
        self.assertEqual(val["n_lines"], 4)
        # Ensure secret keys are not present in returned dict
        self.assertNotIn("ABCD-EFGH", json.dumps(val))

        # Test invalid structure
        bad_lic = os.path.join(self.tmp_dir, "bad_license.txt")
        with open(bad_lic, "w") as f:
            f.write("invalid content\n")
        val_bad = validate_license(bad_lic)
        self.assertFalse(val_bad["ok"])

    def test_system_readiness_capabilities(self):
        """Test 7 scientific capability evaluations and dependency graph."""
        cfg = {
            "python_valid": True,
            "workspace_valid": True,
            "workspace_free_gb": 80.0,
            "pipeline_valid": True,
            "freesurfer_valid": True,
            "license_valid": True,
            "dcm2niix_valid": True,
            "vault_valid": True,
            "vault_connected": True,
            "pensieve_valid": True
        }
        readiness = SystemReadinessService.evaluate_capabilities(cfg, {})
        self.assertTrue(readiness["ready"])
        self.assertTrue(readiness["full_clinical_ready"])
        self.assertEqual(readiness["blockers_count"], 0)

        caps = readiness["capabilities"]
        self.assertTrue(caps["can_launch"]["ready"])
        self.assertTrue(caps["can_import"]["ready"])
        self.assertTrue(caps["can_run_albus"]["ready"])
        self.assertTrue(caps["can_run_pipeline"]["ready"])
        self.assertTrue(caps["can_review"]["ready"])
        self.assertTrue(caps["can_save_annotations"]["ready"])
        self.assertTrue(caps["can_archive"]["ready"])

        # Test dependency map
        deps = SystemReadinessService.get_dependency_map()
        self.assertGreaterEqual(len(deps), 7)

    def test_sanitized_diagnostic_export(self):
        """Test diagnostic export generation and Markdown formatting."""
        report = DiagnosticExportService.generate_report(self.state_mgr, self.discovery_svc, SystemReadinessService)
        self.assertIn("meta", report)
        self.assertIn("host_system", report)
        self.assertIn("readiness", report)

        md = DiagnosticExportService.format_markdown(report)
        self.assertIn("# PERCIVAL System Diagnostic Report", md)
        self.assertIn("Granular Capabilities", md)

    def test_setup_api_handlers(self):
        """Test the setup_get and setup_post request handlers in css_app.py."""
        app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)
        import css_app
        setup_get = css_app.setup_get
        setup_post = css_app.setup_post

        # 1. Lifecycle GET
        life = setup_get("lifecycle", {})
        self.assertIn("state", life)
        self.assertIn("app_version", life)
        self.assertIn("allow_dashboard", life)

        # 2. Discovery GET
        disc = setup_get("discovery", {})
        self.assertTrue(disc["ok"])
        self.assertIn("system", disc["discovery"])
        self.assertIn("python", disc["discovery"])

        # 3. Component validation POST
        v_py = setup_post("validate_component", {"component": "python", "path": sys.executable})
        self.assertTrue(v_py["ok"])

        # 4. Save config POST
        s_res = setup_post("save_config", {"candidate_redetection": True, "candidate_calling": True})
        self.assertTrue(s_res["ok"])

        # 5. Diagnostics GET
        diag = setup_get("diagnostics", {})
        self.assertTrue(diag["ok"])
        self.assertIn("report", diag)
        self.assertIn("markdown", diag)


if __name__ == "__main__":
    unittest.main()
