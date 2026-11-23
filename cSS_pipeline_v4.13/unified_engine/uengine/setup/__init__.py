"""PERCIVAL Setup Center, Discovery, and Configuration Subsystem.

Mission ID: PERCIVAL-SETUP-REDESIGN-2026
"""

from .models import SetupStateEnum, SetupMode, InstallationCandidate, ReadinessCapability, DependencyNode
from .setup_state_manager import SetupStateManager, CURRENT_APP_VERSION
from .validators import (
    validate_python,
    validate_pipeline,
    validate_freesurfer,
    validate_license,
    validate_mri_tool,
    validate_workspace,
    validate_vault,
    validate_pensieve
)
from .installation_discovery import InstallationDiscoveryService
from .readiness_service import SystemReadinessService
from .diagnostic_export import DiagnosticExportService

__all__ = [
    "SetupStateEnum",
    "SetupMode",
    "InstallationCandidate",
    "ReadinessCapability",
    "DependencyNode",
    "SetupStateManager",
    "CURRENT_APP_VERSION",
    "validate_python",
    "validate_pipeline",
    "validate_freesurfer",
    "validate_license",
    "validate_mri_tool",
    "validate_workspace",
    "validate_vault",
    "validate_pensieve",
    "InstallationDiscoveryService",
    "SystemReadinessService",
    "DiagnosticExportService",
]
