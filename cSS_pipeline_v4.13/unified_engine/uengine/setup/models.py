"""Data models and enums for PERCIVAL Setup Wizard and System Configuration.

Mission ID: PERCIVAL-SETUP-REDESIGN-2026
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, Any, List, Optional


class SetupStateEnum(str, Enum):
    """Authoritative states of the setup lifecycle."""
    FIRST_LAUNCH = "FIRST_LAUNCH"
    DISCOVERY_IN_PROGRESS = "DISCOVERY_IN_PROGRESS"
    SETUP_IN_PROGRESS = "SETUP_IN_PROGRESS"
    SETUP_BLOCKED = "SETUP_BLOCKED"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
    SETUP_COMPLETED = "SETUP_COMPLETED"
    RECONFIGURATION_REQUIRED = "RECONFIGURATION_REQUIRED"


class SetupMode(str, Enum):
    """The user interaction mode for configuration."""
    GUIDED_SETUP = "GUIDED_SETUP"
    SYSTEM_CONFIG = "SYSTEM_CONFIG"


@dataclass
class InstallationCandidate:
    """A discovered or configured software installation."""
    component_id: str             # e.g., 'python', 'freesurfer', 'license', 'pipeline', 'dcm2niix', 'vault'
    name: str                     # Human-readable name
    path: str                     # Directory or file path
    executable_path: Optional[str] = None
    version: str = "unknown"
    is_valid: bool = False
    validation_message: str = ""
    is_preferred: bool = False
    discovery_method: str = "manual"  # 'auto_path', 'standard_location', 'env_var', 'manual_entry'
    last_validated: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReadinessCapability:
    """Scientific readiness capability for clinical/research workflows."""
    id: str                       # e.g. 'can_launch', 'can_import', 'can_run_pipeline'
    label: str
    ready: bool
    required_components: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DependencyNode:
    """A node in the system configuration dependency map."""
    component_id: str
    label: str
    depends_on: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    status: str = "ready"         # 'ready', 'warning', 'blocked'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
