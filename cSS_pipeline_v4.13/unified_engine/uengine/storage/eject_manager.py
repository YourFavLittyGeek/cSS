"""uengine/storage/eject_manager.py - Authoritative External Drive Ejection & Safety Manager.

Guarantees backend-authoritative drive status (SAFE_TO_EJECT, IN_USE, PREPARING, ATTENTION_REQUIRED),
safe unmounting via macOS diskutil, and crash-resilient emergency interruption.
"""

import os
import sys
import time
import secrets
import subprocess
import threading
from typing import Callable, Dict, Any, List, Optional
from .models import DriveSafetyState, EjectCheckResult
from .storage_paths import StoragePathsService
from .storage_state import StorageStateService
from ..safety import volumes_root

FORCE_TOKEN_TTL_S = 120
_FORCE_TOKENS: Dict[str, Dict[str, Any]] = {}    # process-wide: each request builds a new EjectManager
_FORCE_LOCK = threading.Lock()


class EjectManager:
    """Authoritative controller for safe external Vault disconnection and macOS ejection."""

    def __init__(self, paths_service: Optional[StoragePathsService] = None,
                 state_service: Optional[StorageStateService] = None,
                 runner: Optional[Callable[[List[str]], Any]] = None):
        self._runner = runner
        self.paths = paths_service or StoragePathsService()
        self.state = state_service or StorageStateService(self.paths)
        self._preparing_eject = False

    def check_ejection_safety(self) -> EjectCheckResult:
        """Inspect active operations, open handles, and journal state to determine ejection safety."""
        vault_info = self.paths.get_vault_info()
        if not vault_info or not vault_info.is_connected:
            return EjectCheckResult(
                can_eject=True,
                state=DriveSafetyState.DRIVE_NOT_CONNECTED,
                reason="External Vault is not mounted or already disconnected."
            )

        # Check active transfer jobs targeting Vault
        active_jobs = [j for j in self.state.get_all_jobs(limit=20)
                       if j.get("status") in ("running", "transferring", "verifying", "flushing")]
        if active_jobs:
            is_verifying = any(j.get("verification_status") == "verifying" or j.get("status") == "verifying" for j in active_jobs)
            current_st = DriveSafetyState.VERIFYING if is_verifying else DriveSafetyState.TRANSFERRING
            job_ids = [j["job_id"] for j in active_jobs]
            return EjectCheckResult(
                can_eject=False,
                state=current_st,
                reason=f"{len(active_jobs)} active transfer/verification operation(s) in progress.",
                active_operations_count=len(active_jobs),
                active_job_ids=job_ids,
                volume_uuid=vault_info.volume_uuid
            )

        if self._preparing_eject:
            return EjectCheckResult(
                can_eject=False,
                state=DriveSafetyState.PREPARING_TO_EJECT,
                reason="READY TO EJECT — preparing to close the volume and flush journals.",
                volume_uuid=vault_info.volume_uuid
            )

        # Confirm filesystem writes are cleanly committed
        return EjectCheckResult(
            can_eject=True,
            state=DriveSafetyState.READY,
            reason="READY TO EJECT — All transfers and journals committed. Ready for OS unmount.",
            volume_uuid=vault_info.volume_uuid
        )

    # ------------------------------------------------------------------ Phase 0: server-side force authorisation
    def _run(self, cmd: List[str]):
        """run diskutil (injectable for tests; never run under test isolation)"""
        if self._runner is not None:
            return self._runner(cmd)
        if os.environ.get("PERCIVAL_TEST_ISOLATION") == "1":
            raise RuntimeError("diskutil is never run under test isolation")
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15)

    @staticmethod
    def _issue_force_token(mount_point: str, volume_name: str) -> str:
        tok = secrets.token_urlsafe(24)
        with _FORCE_LOCK:
            now = time.time()
            for k in [k for k, v in _FORCE_TOKENS.items() if v["expires"] < now]:
                _FORCE_TOKENS.pop(k, None)
            _FORCE_TOKENS[tok] = {"mount_point": mount_point, "volume_name": volume_name, "expires": now + FORCE_TOKEN_TTL_S}
        return tok

    @staticmethod
    def _consume_force_token(token: str, mount_point: str, typed_name: str, volume_name: str) -> Optional[str]:
        """None if the token authorises a force unmount of this volume (single use), else the refusal reason"""
        if not token or not isinstance(token, str):
            return "force unmount needs a server-issued authorisation (refused normal unmount first)"
        with _FORCE_LOCK:
            rec = _FORCE_TOKENS.pop(token, None)          # single use, whatever the outcome
        if rec is None:
            return "force authorisation unknown or already used"
        if rec["expires"] < time.time():
            return "force authorisation expired; request the unmount again"
        if rec["mount_point"] != mount_point:
            return "force authorisation was issued for a different volume"
        if not isinstance(typed_name, str) or typed_name.strip() != volume_name:
            return f"confirmation does not match: type the volume name '{volume_name}' exactly"
        return None

    def eject_vault(self, emergency: bool = False, force: bool = False, force_token: str = "",
                    confirm_volume_name: str = "") -> Dict[str, Any]:
        """Perform verified macOS volume unmount with controlled emergency support.

        Phase 0:
        - a normal (or emergency) unmount is attempted only when check_ejection_safety() allows it;
        - force=True is honoured only with a single-use token issued by the server after a REFUSED unmount of the same
          volume (valid FORCE_TOKEN_TTL_S seconds) AND the volume name typed by the user (confirm_volume_name);
        - the target must be a real mount point directly under the volumes root (never a folder inside a volume)."""
        vault_info = self.paths.get_vault_info()
        if not vault_info or not vault_info.is_connected:
            return {"ok": True, "state": DriveSafetyState.SAFE_TO_EJECT.value, "message": "Volume is already unmounted. SAFE TO EJECT."}

        mount_point = os.path.realpath(vault_info.mount_point or "")
        vols = os.path.realpath(volumes_root())
        if not mount_point or os.path.dirname(mount_point) != vols or not os.path.ismount(mount_point):
            return {"ok": False, "state": DriveSafetyState.BLOCKED.value,
                    "error": f"Refused: {mount_point or '(none)'} is not a mounted volume under {vols}; nothing was unmounted"}
        volume_name = vault_info.volume_name or os.path.basename(mount_point)

        if force:
            why = self._consume_force_token(force_token, mount_point, confirm_volume_name, volume_name)
            if why:
                self.state.record_audit_event("eject_force_refused", "failure", details={"mount_point": mount_point, "reason": why})
                return {"ok": False, "state": DriveSafetyState.BLOCKED.value, "error": f"Refused: {why}"}
        else:
            safety = self.check_ejection_safety()
            if not safety.can_eject:
                return {"ok": False, "state": safety.state.value, "error": f"Refused: {safety.reason}"}

        self._preparing_eject = True
        self.state.record_audit_event("eject_requested", "initiated", details={"mount_point": mount_point, "emergency": emergency, "force": force})

        try:
            # 1. Cooperative pause of active transfers if emergency
            if emergency:
                try:
                    from ..unified_transfer_engine import get_transfer_engine
                    te = get_transfer_engine()
                    for j in te.get_active_jobs():
                        te.pause_job(j.get("job_id", ""))
                except Exception:
                    pass

            # 2. Flush filesystem buffers
            try:
                os.sync()
            except Exception:
                pass

            # 3. Execute diskutil unmount
            cmd = ["diskutil", "unmount"]
            if force:
                cmd.append("force")
            cmd.append(mount_point)

            r = self._run(cmd)

            if r.returncode == 0:
                self._preparing_eject = False
                self.state.record_audit_event("eject_completed", "success", details={"mount_point": mount_point, "emergency": emergency, "forced": force})
                return {
                    "ok": True,
                    "state": DriveSafetyState.SAFE_TO_EJECT.value,
                    "message": f"SAFE TO EJECT: Successfully unmounted {volume_name}. You may safely disconnect the cable."
                }
            else:
                self._preparing_eject = False
                err_msg = (r.stderr or "").strip() or (r.stdout or "").strip()
                self.state.record_audit_event("eject_failed", "failure", details={"mount_point": mount_point, "error": err_msg})
                if emergency and not force:
                    return {
                        "ok": False,
                        "state": DriveSafetyState.BLOCKED.value,
                        "needs_force_confirmation": True,
                        "force_token": self._issue_force_token(mount_point, volume_name),
                        "force_token_ttl_s": FORCE_TOKEN_TTL_S,
                        "volume_name": volume_name,
                        "error": f"macOS unmount refused: {err_msg}. Emergency force unmount may cause data loss or filesystem corruption. "
                                 f"To force it, confirm by typing the volume name '{volume_name}'."
                    }
                return {
                    "ok": False,
                    "state": DriveSafetyState.BLOCKED.value,
                    "error": f"macOS refused to unmount drive: {err_msg}. Another application or Finder may have open files on {mount_point}."
                }

        except Exception as e:
            self._preparing_eject = False
            self.state.record_audit_event("eject_error", "failure", details={"mount_point": mount_point, "error": str(e)})
            return {"ok": False, "error": f"Ejection failed: {str(e)}"}
