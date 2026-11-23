"""Persistent state manager for PERCIVAL First-Launch Setup and Configuration.

Mission ID: PERCIVAL-SETUP-REDESIGN-2026
"""

import os
import json
import time
import shutil
import datetime
from typing import Dict, Any, Optional, List, Tuple
from .models import SetupStateEnum, SetupMode

CURRENT_APP_VERSION = "v5.26-Master-Setup-Rebuild"


class SetupStateManager:
    """Controls lifecycle state transitions, resume behavior, and configuration persistence."""

    def __init__(self, workspace_root: Optional[str] = None, vault_root: Optional[str] = None):
        self.workspace_root = os.path.abspath(workspace_root or os.path.expanduser("~/Percival_project"))
        self.vault_root = os.path.abspath(vault_root) if vault_root else None
        self.app_data = os.path.join(self.workspace_root, "app_data")
        os.makedirs(self.app_data, exist_ok=True)
        self.state_file = os.path.join(self.app_data, "setup_state.json")
        self.legacy_done_file = os.path.join(self.app_data, "setup_done.json")
        self._state: Dict[str, Any] = self._load_or_initialize_state()

    def _default_state(self) -> Dict[str, Any]:
        return {
            "state": SetupStateEnum.FIRST_LAUNCH.value,
            "mode": SetupMode.GUIDED_SETUP.value,
            "is_first_launch": True,
            "completed": False,
            "completed_at": None,
            "app_version": CURRENT_APP_VERSION,
            "current_step": 1,
            "last_completed_step": 0,
            "validated_config": {},
            "previous_config": {},
            "pending_config": {},
            "discovery_cache": {},
            "outstanding_actions": [],
            "last_validation_time": 0.0,
            "readiness_summary": {},
            "updated_at": time.time(),
            "history": []
        }

    def _load_or_initialize_state(self) -> Dict[str, Any]:
        if os.path.isfile(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    state = json.load(f)
                    # Verify required keys exist
                    for k, v in self._default_state().items():
                        if k not in state:
                            state[k] = v
                    return state
            except Exception:
                pass

        # Check for legacy setup_done.json or existing research data
        default = self._default_state()
        if self._has_existing_installation():
            default["state"] = SetupStateEnum.SETUP_COMPLETED.value
            default["is_first_launch"] = False
            default["completed"] = True
            default["completed_at"] = datetime.datetime.now().isoformat()
            default["last_completed_step"] = 7
            default["current_step"] = 7
            default["history"].append({
                "timestamp": time.time(),
                "event": "legacy_installation_detected_and_migrated",
                "version": CURRENT_APP_VERSION
            })
            self._save(default)
            return default

        self._save(default)
        return default

    def _has_existing_installation(self) -> bool:
        """Inspect if the system already has completed setup, studies, or Pensieve databases."""
        if os.path.isfile(self.legacy_done_file):
            return True

        # Check for existing studies or active database
        db_path = os.path.join(self.app_data, "pensieve.db")
        pat_file = os.path.join(self.app_data, "patients.json")
        if os.path.isfile(db_path) and os.path.getsize(db_path) > 4096:
            return True
        if os.path.isfile(pat_file):
            try:
                with open(pat_file, "r") as pf:
                    pats = json.load(pf)
                    if isinstance(pats, list) and len(pats) > 0:
                        return True
            except Exception:
                pass

        # Check if external vault already has studies (associated with standard project)
        vault_root = self.vault_root or ("/Volumes/Percival/PERCIVAL_VAULT" if self.workspace_root == os.path.abspath(os.path.expanduser("~/Percival_project")) else None)
        if vault_root and (os.path.isdir(os.path.join(vault_root, "studies")) or os.path.isdir(os.path.join(vault_root, "PENSIEVE"))):
            return True

        return False

    def _save(self, state: Optional[Dict[str, Any]] = None) -> None:
        if state is not None:
            self._state = state
        self._state["updated_at"] = time.time()
        tmp_f = self.state_file + ".tmp"
        try:
            with open(tmp_f, "w") as f:
                json.dump(self._state, f, indent=2)
            os.replace(tmp_f, self.state_file)
        except Exception:
            pass

    def get_state(self) -> Dict[str, Any]:
        """Return a snapshot of the persistent setup state."""
        return dict(self._state)

    def detect_launch_mode(self, app_version: str = CURRENT_APP_VERSION) -> Dict[str, Any]:
        """Evaluates launch conditions: fresh, resume, updated, or ready."""
        state = self.get_state()
        recorded_version = state.get("app_version", "")

        # 1. Application update detection
        if state.get("completed") and recorded_version != app_version:
            state["app_version"] = app_version
            state["history"].append({
                "timestamp": time.time(),
                "event": "application_updated",
                "from_version": recorded_version,
                "to_version": app_version
            })
            self._save(state)
            return {
                "launch_type": "application_update",
                "state": state["state"],
                "allow_dashboard": True,
                "notice": f"PERCIVAL updated to {app_version}. Existing configuration and research data preserved."
            }

        # 2. Already completed setup
        if state.get("completed"):
            return {
                "launch_type": "standard_launch",
                "state": state["state"],
                "allow_dashboard": True,
                "notice": None
            }

        # 3. Setup in progress (resume)
        if state.get("current_step", 1) > 1 or state.get("state") == SetupStateEnum.SETUP_IN_PROGRESS.value:
            return {
                "launch_type": "setup_resume",
                "state": SetupStateEnum.SETUP_IN_PROGRESS.value,
                "allow_dashboard": False,
                "resume_step": state.get("current_step", 1),
                "notice": f"Resuming Guided Setup at Step {state.get('current_step', 1)}."
            }

        # 4. Fresh first launch
        return {
            "launch_type": "first_launch",
            "state": SetupStateEnum.FIRST_LAUNCH.value,
            "allow_dashboard": False,
            "notice": "Welcome to PERCIVAL. Guided Setup is required before first use."
        }

    def set_step(self, step: int, partial_config: Optional[Dict[str, Any]] = None) -> None:
        """Advance or navigate between wizard steps while saving partial progress."""
        self._state["current_step"] = step
        if step > self._state.get("last_completed_step", 0) + 1:
            self._state["last_completed_step"] = step - 1
        self._state["state"] = SetupStateEnum.SETUP_IN_PROGRESS.value
        self._state["is_first_launch"] = False

        if partial_config:
            self._state["pending_config"].update(partial_config)

        self._state["history"].append({
            "timestamp": time.time(),
            "event": "step_changed",
            "step": step
        })
        self._save()

    def update_validated_config(self, config_updates: Dict[str, Any]) -> None:
        """Store newly validated configuration values."""
        # Archive previous configuration for rollback
        self._state["previous_config"] = dict(self._state.get("validated_config", {}))
        self._state["validated_config"].update(config_updates)
        self._state["last_validation_time"] = time.time()
        self._save()

    def revert_to_previous_config(self) -> Tuple[bool, str]:
        """Revert the last configuration change."""
        prev = self._state.get("previous_config")
        if not prev:
            return False, "No previous configuration snapshot available for rollback."
        self._state["validated_config"] = dict(prev)
        self._state["history"].append({
            "timestamp": time.time(),
            "event": "configuration_reverted"
        })
        self._save()
        return True, "Reverted configuration to previous working state."

    def cache_discovery(self, discovery_results: Dict[str, Any]) -> None:
        """Persist discovery candidates non-destructively."""
        self._state["discovery_cache"] = discovery_results
        self._save()

    def mark_completed(self, readiness_summary: Dict[str, Any]) -> None:
        """Finalize first-launch setup and enable normal application access."""
        ready = readiness_summary.get("ready", False)
        target_state = SetupStateEnum.SETUP_COMPLETED.value if ready else SetupStateEnum.READY_WITH_WARNINGS.value

        self._state["state"] = target_state
        self._state["completed"] = True
        self._state["completed_at"] = datetime.datetime.now().isoformat()
        self._state["current_step"] = 7
        self._state["last_completed_step"] = 7
        self._state["readiness_summary"] = readiness_summary
        self._state["history"].append({
            "timestamp": time.time(),
            "event": "setup_completed",
            "state": target_state
        })

        # Also write backward-compatible setup_done.json
        try:
            with open(self.legacy_done_file, "w") as f:
                json.dump({
                    "done": self._state["completed_at"],
                    "ready": ready,
                    "version": CURRENT_APP_VERSION
                }, f, indent=2)
        except Exception:
            pass

        self._save()

    def reset_to_first_launch(self) -> None:
        """Explicit admin reset to force re-running the guided setup."""
        new_state = self._default_state()
        new_state["previous_config"] = dict(self._state.get("validated_config", {}))
        new_state["history"].append({
            "timestamp": time.time(),
            "event": "admin_reset_to_first_launch"
        })
        self._save(new_state)

    def is_dashboard_allowed(self) -> bool:
        """Checks if normal application dashboard can be opened."""
        return self._state.get("completed", False) or self._state.get("state") in (
            SetupStateEnum.SETUP_COMPLETED.value,
            SetupStateEnum.READY_WITH_WARNINGS.value
        )
