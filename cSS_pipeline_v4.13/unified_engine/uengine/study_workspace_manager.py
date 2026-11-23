"""uengine/study_workspace_manager.py - Central Study Workspace Manager & Sequential Queue

Architectural backbone managing the end-to-end lifecycle of every MRI study in PERCIVAL:
1. Validated state transitions across 18 explicit study lifecycle phases.
2. Controlled Mac SSD high-speed staging and intelligent capacity estimation.
3. Integration with ALBUS, LUMOS, NOX, PERCIVAL Core, MRI viewer, Pensieve, and Archive.
4. Sequential study-processing queue: stage -> process -> expert review -> archive & verify -> local clean.
5. Crash recovery and durable study manifest tracking.
"""

import os
import sys
import json
import time
import shutil
import hashlib
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple, Set

from .unified_transfer_engine import get_transfer_engine, UnifiedTransferEngine


class StudyLifecycleState(str, Enum):
    DISCOVERED = "Discovered"
    REGISTERED = "Registered"
    AWAITING_STAGING = "Awaiting staging"
    STAGING = "Staging"
    STAGED = "Staged"
    READY_FOR_PROCESSING = "Ready for processing"
    PROCESSING = "Processing"
    PROCESSING_INTERRUPTED = "Processing interrupted"
    PROCESSING_COMPLETED = "Processing completed"
    AWAITING_EXPERT_REVIEW = "Awaiting expert review"
    UNDER_EXPERT_REVIEW = "Under expert review"
    REVIEW_COMPLETED = "Review completed"
    AWAITING_ARCHIVAL = "Awaiting archival"
    ARCHIVING = "Archiving"
    ARCHIVED = "Archived"
    ARCHIVE_VERIFICATION_FAILED = "Archive verification failed"
    RECOVERY_REQUIRED = "Recovery required"
    ERROR = "Error"


# Validated state transition map
VALID_TRANSITIONS: Dict[str, Set[str]] = {
    StudyLifecycleState.DISCOVERED.value: {
        StudyLifecycleState.REGISTERED.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.REGISTERED.value: {
        StudyLifecycleState.AWAITING_STAGING.value,
        StudyLifecycleState.STAGING.value,
        StudyLifecycleState.READY_FOR_PROCESSING.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.AWAITING_STAGING.value: {
        StudyLifecycleState.STAGING.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.STAGING.value: {
        StudyLifecycleState.STAGED.value,
        StudyLifecycleState.RECOVERY_REQUIRED.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.STAGED.value: {
        StudyLifecycleState.READY_FOR_PROCESSING.value,
        StudyLifecycleState.PROCESSING.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.READY_FOR_PROCESSING.value: {
        StudyLifecycleState.PROCESSING.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.PROCESSING.value: {
        StudyLifecycleState.PROCESSING_COMPLETED.value,
        StudyLifecycleState.PROCESSING_INTERRUPTED.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.PROCESSING_INTERRUPTED.value: {
        StudyLifecycleState.PROCESSING.value,
        StudyLifecycleState.RECOVERY_REQUIRED.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.PROCESSING_COMPLETED.value: {
        StudyLifecycleState.AWAITING_EXPERT_REVIEW.value,
        StudyLifecycleState.UNDER_EXPERT_REVIEW.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.AWAITING_EXPERT_REVIEW.value: {
        StudyLifecycleState.UNDER_EXPERT_REVIEW.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.UNDER_EXPERT_REVIEW.value: {
        StudyLifecycleState.REVIEW_COMPLETED.value,
        StudyLifecycleState.AWAITING_EXPERT_REVIEW.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.REVIEW_COMPLETED.value: {
        StudyLifecycleState.AWAITING_ARCHIVAL.value,
        StudyLifecycleState.ARCHIVING.value,
        StudyLifecycleState.UNDER_EXPERT_REVIEW.value, # Allow re-review if needed
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.AWAITING_ARCHIVAL.value: {
        StudyLifecycleState.ARCHIVING.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.ARCHIVING.value: {
        StudyLifecycleState.ARCHIVED.value,
        StudyLifecycleState.ARCHIVE_VERIFICATION_FAILED.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.ARCHIVED.value: {
        StudyLifecycleState.UNDER_EXPERT_REVIEW.value, # Review archived study
        StudyLifecycleState.AWAITING_STAGING.value,    # Re-stage for re-processing
    },
    StudyLifecycleState.ARCHIVE_VERIFICATION_FAILED.value: {
        StudyLifecycleState.ARCHIVING.value,
        StudyLifecycleState.RECOVERY_REQUIRED.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.RECOVERY_REQUIRED.value: {
        StudyLifecycleState.AWAITING_STAGING.value,
        StudyLifecycleState.READY_FOR_PROCESSING.value,
        StudyLifecycleState.ERROR.value
    },
    StudyLifecycleState.ERROR.value: {
        StudyLifecycleState.REGISTERED.value,
        StudyLifecycleState.AWAITING_STAGING.value,
        StudyLifecycleState.RECOVERY_REQUIRED.value,
    }
}


def compute_file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


class StudyWorkspaceManager:
    """Central authority controlling study lifecycle, active SSD workspace, and HDD archival."""

    def __init__(self, base_dir: str, vault_root: Optional[str] = None):
        self.base_dir = os.path.abspath(base_dir)
        self.app_data = os.path.join(self.base_dir, "app_data")
        os.makedirs(self.app_data, exist_ok=True)
        self.ledger_file = os.path.join(self.app_data, "study_workspace_ledger.json")
        self.queue_file = os.path.join(self.app_data, "sequential_study_queue.json")
        self.vault_root = os.path.abspath(vault_root) if vault_root else None
        self._ledger: Dict[str, Dict[str, Any]] = self._load_ledger()
        self._queue: List[Dict[str, Any]] = self._load_queue()

    def _load_ledger(self) -> Dict[str, Dict[str, Any]]:
        if os.path.exists(self.ledger_file):
            try:
                with open(self.ledger_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_ledger(self) -> None:
        tmp = self.ledger_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._ledger, f, indent=2)
        os.replace(tmp, self.ledger_file)

    def _load_queue(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.queue_file):
            try:
                with open(self.queue_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save_queue(self) -> None:
        tmp = self.queue_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._queue, f, indent=2)
        os.replace(tmp, self.queue_file)

    # -------------------------------------------------------------------------
    # Study Registration & State Transition Management
    # -------------------------------------------------------------------------
    def register_study(self, study_id: str, original_mri_location: str,
                       initial_state: str = StudyLifecycleState.REGISTERED.value,
                       metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Register a study with permanent ID, source path, and initial state."""
        study_id = str(study_id).strip()
        if not study_id:
            raise ValueError("study_id cannot be empty")

        now = time.time()
        rec = self._ledger.get(study_id)
        if rec:
            # Update source location if previously not set
            if original_mri_location and not rec.get("original_mri_location"):
                rec["original_mri_location"] = os.path.abspath(original_mri_location)
            rec["updated_at"] = now
            self._save_ledger()
            return rec

        active_ws = os.path.join(self.base_dir, "work", study_id)
        archive_loc = os.path.join(self.vault_root, "studies", study_id) if self.vault_root else ""

        rec = {
            "study_id": study_id,
            "state": initial_state,
            "original_mri_location": os.path.abspath(original_mri_location) if original_mri_location else "",
            "active_workspace_location": active_ws,
            "hdd_archive_location": archive_loc,
            "file_count": 0,
            "total_size_bytes": 0,
            "checksums": {},
            "processing_status": {"stage": "none", "percent": 0, "completed": False},
            "review_status": {
                "candidates_reviewed": False,
                "missed_lesions_assessed": False,
                "review_completed": False,
                "reviewer_id": None
            },
            "active_job_references": [],
            "last_successful_operation": "registered",
            "archive_status": "not_archived",
            "recovery_status": "clean",
            "estimated_space_mb": 0.0,
            "created_at": now,
            "updated_at": now,
            "metadata": metadata or {}
        }
        self._ledger[study_id] = rec
        self._save_ledger()
        return rec

    def transition_state(self, study_id: str, target_state: str,
                         reason: Optional[str] = None,
                         extra_data: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
        """Validate and apply a lifecycle state transition for a study."""
        if study_id not in self._ledger:
            return False, f"Study not found in workspace ledger: {study_id}"

        rec = self._ledger[study_id]
        current_state = rec.get("state", StudyLifecycleState.REGISTERED.value)

        # Self-transition is an idempotent no-op
        if current_state == target_state:
            rec["updated_at"] = time.time()
            if extra_data:
                rec.update(extra_data)
            self._save_ledger()
            return True, f"Idempotent state confirmation: {target_state}"

        allowed = VALID_TRANSITIONS.get(current_state, set())
        if target_state not in allowed:
            # Special case: allow admin error/recovery override
            if target_state in (StudyLifecycleState.ERROR.value, StudyLifecycleState.RECOVERY_REQUIRED.value):
                allowed.add(target_state)
            else:
                return False, f"Illegal state transition from '{current_state}' to '{target_state}'. Allowed: {sorted(list(allowed))}"

        rec["state"] = target_state
        rec["last_successful_operation"] = reason or f"transitioned_to_{target_state.lower().replace(' ', '_')}"
        rec["updated_at"] = time.time()
        if extra_data:
            rec.update(extra_data)

        self._save_ledger()
        return True, f"Transitioned to {target_state}"

    def get_study(self, study_id: str) -> Optional[Dict[str, Any]]:
        return self._ledger.get(study_id)

    def list_studies(self, state: Optional[str] = None) -> List[Dict[str, Any]]:
        studies = list(self._ledger.values())
        if state:
            studies = [s for s in studies if s.get("state") == state]
        return sorted(studies, key=lambda x: x.get("updated_at", 0), reverse=True)

    def discover_source_studies(self, search_paths: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Discover original MRI studies from source locations without modifying or copying them."""
        paths_to_scan = search_paths or [
            "/Volumes/Percival/Dicom",
            os.path.join(self.vault_root, "original_mri") if self.vault_root else "",
            os.path.join(self.vault_root, "MRI", "Originals") if self.vault_root else "",
            os.path.join(self.base_dir, "raw", "import_source_preserved"),
            os.path.join(self.base_dir, "app_data", "import_src")
        ]
        discovered = []
        seen_paths = set()

        for base_p in paths_to_scan:
            if not base_p or not os.path.isdir(base_p):
                continue
            try:
                for entry in sorted(os.listdir(base_p)):
                    if entry.startswith("."):
                        continue
                    sp = os.path.join(base_p, entry)
                    if sp in seen_paths:
                        continue
                    seen_paths.add(sp)

                    if os.path.isdir(sp):
                        # Count DICOM and NIfTI files
                        all_files = [os.path.join(r, f) for r, _, fs in os.walk(sp) for f in fs if not f.startswith(".")]
                        dicom_files = [f for f in all_files if f.lower().endswith((".dcm", ".ima")) or "dicom" in f.lower()]
                        nifti_files = [f for f in all_files if f.lower().endswith((".nii", ".nii.gz"))]
                        total_sz = sum(os.path.getsize(f) for f in all_files if os.path.isfile(f))

                        if len(dicom_files) > 0 or len(nifti_files) > 0 or len(all_files) > 0:
                            # Detect series
                            subdirs = [d for d in os.listdir(sp) if os.path.isdir(os.path.join(sp, d)) and not d.startswith(".")]
                            is_registered = entry in self._ledger

                            discovered.append({
                                "study_id": entry,
                                "source_path": sp,
                                "source_type": "DICOM" if len(dicom_files) >= len(nifti_files) else "NIfTI",
                                "total_files": len(all_files),
                                "dicom_count": len(dicom_files),
                                "nifti_count": len(nifti_files),
                                "total_size_bytes": total_sz,
                                "total_size_mb": round(total_sz / (1024 * 1024), 2),
                                "series_detected": subdirs if subdirs else ["single_folder"],
                                "is_registered": is_registered,
                                "current_state": self._ledger[entry]["state"] if is_registered else "Discovered",
                                "readable": os.access(sp, os.R_OK)
                            })
            except Exception:
                continue

        return discovered

    # -------------------------------------------------------------------------
    # Capacity Estimation & Staging (Mac SSD)
    # -------------------------------------------------------------------------
    def estimate_capacity(self, study_id: str, source_paths: Optional[List[str]] = None) -> Dict[str, Any]:
        """Estimate workspace requirements considering preprocessing, FreeSurfer/SynthSeg, ALBUS, LUMOS, NOX."""
        rec = self._ledger.get(study_id, {})
        paths = source_paths or []
        if not paths and rec.get("original_mri_location"):
            paths = [rec["original_mri_location"]]

        total_source_bytes = 0
        for p in paths:
            if os.path.isfile(p):
                total_source_bytes += os.path.getsize(p)
            elif os.path.isdir(p):
                for root, _, files in os.walk(p):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            total_source_bytes += os.path.getsize(fp)
                        except Exception:
                            pass

        # Complete pipeline expansion multiplier:
        # Preprocessing + Resampled SWI/T1 + SynthSeg (1.5x) + Candidate patches (1.2x) + Feature/Viewer caches (1.3x) = ~5.0x
        expansion_factor = 5.0
        projected_required_bytes = int(max(total_source_bytes * expansion_factor, 500 * (1024**2))) # At least 500MB
        projected_required_mb = round(projected_required_bytes / (1024**2), 1)

        usage = shutil.disk_usage(self.base_dir)
        free_bytes = usage.free
        free_mb = round(free_bytes / (1024**2), 1)
        # Emergency reserve: 5.0 GB minimum required headroom
        reserve_bytes = 5 * (1024**3)
        admissible = (free_bytes - projected_required_bytes) > reserve_bytes

        if rec:
            rec["estimated_space_mb"] = projected_required_mb
            self._save_ledger()

        return {
            "study_id": study_id,
            "source_bytes": total_source_bytes,
            "source_mb": round(total_source_bytes / (1024**2), 1),
            "projected_required_bytes": projected_required_bytes,
            "projected_required_mb": projected_required_mb,
            "ssd_free_mb": free_mb,
            "emergency_reserve_mb": round(reserve_bytes / (1024**2), 1),
            "admissible": admissible,
            "warning": None if admissible else f"Insufficient SSD space for study {study_id}: requires {projected_required_mb} MB with 5.0 GB reserve; only {free_mb} MB available."
        }

    def stage_study(self, study_id: str, source_paths: Optional[List[str]] = None,
                    verify: bool = True) -> Tuple[bool, str, Dict[str, Any]]:
        """Stage input MRI from external drive into local high-speed Mac SSD workspace."""
        if study_id not in self._ledger:
            return False, f"Study {study_id} is not registered.", {}

        # 1. Capacity check
        cap = self.estimate_capacity(study_id, source_paths)
        if not cap["admissible"]:
            self.transition_state(study_id, StudyLifecycleState.ERROR.value, reason=cap["warning"])
            return False, cap["warning"], cap

        self.transition_state(study_id, StudyLifecycleState.STAGING.value, reason="staging_started")

        rec = self._ledger[study_id]
        ws_dir = os.path.join(self.base_dir, "work", study_id)
        os.makedirs(ws_dir, exist_ok=True)
        rec["active_workspace_location"] = ws_dir

        paths = source_paths or []
        if not paths and rec.get("original_mri_location"):
            paths = [rec["original_mri_location"]]

        engine = get_transfer_engine(os.path.join(self.base_dir, "app_data", "transfers"))
        staged_manifest = {}
        total_bytes = 0
        file_count = 0

        try:
            for p in paths:
                if not os.path.exists(p):
                    raise FileNotFoundError(f"Source path not found: {p}")

                ok, msg, p_info = engine.transfer_path(
                    src=p,
                    dst=ws_dir,
                    operation="stage",
                    study_id=study_id,
                    verify_sha=verify,
                    preserve_source=True,
                    prefer_clone=True
                )
                if not ok:
                    raise IOError(f"UnifiedTransferEngine staging failed: {msg}")

                total_bytes += p_info.get("completed_bytes", 0)
                file_count += p_info.get("completed_files", 0)

            # Re-index staged directory files for checksum ledger
            for root, _, files in os.walk(ws_dir):
                for f in files:
                    if f.startswith("."):
                        continue
                    fp = os.path.join(root, f)
                    rel = os.path.relpath(fp, ws_dir)
                    csum = compute_file_sha256(fp) if verify else ""
                    staged_manifest[rel] = {"dest": fp, "sha256": csum, "size": os.path.getsize(fp)}

            rec["checksums"] = {k: v["sha256"] for k, v in staged_manifest.items()}
            rec["file_count"] = len(staged_manifest)
            rec["total_size_bytes"] = sum(v["size"] for v in staged_manifest.values())
            rec["updated_at"] = time.time()

            self.transition_state(study_id, StudyLifecycleState.STAGED.value, reason="staging_complete")
            self.transition_state(study_id, StudyLifecycleState.READY_FOR_PROCESSING.value, reason="ready_for_processing")
            return True, f"Successfully staged {rec['file_count']} files for study {study_id}", rec
        except Exception as e:
            self.transition_state(study_id, StudyLifecycleState.ERROR.value, reason=f"Staging failed: {e}")
            return False, f"Staging failed: {e}", {}

    def verify_staged_study(self, study_id: str) -> Tuple[bool, str]:
        """Verify integrity of files in the active SSD workspace against stored checksums."""
        rec = self._ledger.get(study_id)
        if not rec:
            return False, "Study not found"

        ws_dir = rec.get("active_workspace_location")
        if not ws_dir or not os.path.isdir(ws_dir):
            return False, f"Active workspace directory missing: {ws_dir}"

        stored_checksums = rec.get("checksums", {})
        if not stored_checksums:
            return True, "No checksums stored to verify"

        for rel, expected_hash in stored_checksums.items():
            if not expected_hash:
                continue
            fp = os.path.join(ws_dir, rel)
            if not os.path.exists(fp):
                return False, f"Missing staged file: {rel}"
            actual = compute_file_sha256(fp)
            if actual != expected_hash:
                return False, f"Checksum mismatch for {rel}: expected {expected_hash}, got {actual}"

        return True, f"All {len(stored_checksums)} staged files verified successfully"

    # -------------------------------------------------------------------------
    # Expert Review and Archival to External Vault
    # -------------------------------------------------------------------------
    def record_review_status(self, study_id: str, candidates_reviewed: bool,
                            missed_lesions_assessed: bool,
                            reviewer_id: Optional[str] = None) -> Tuple[bool, str]:
        """Record review status in central workspace manager."""
        rec = self._ledger.get(study_id)
        if not rec:
            return False, "Study not found"

        fully_reviewed = bool(candidates_reviewed and missed_lesions_assessed)
        rec["review_status"] = {
            "candidates_reviewed": candidates_reviewed,
            "missed_lesions_assessed": missed_lesions_assessed,
            "review_completed": fully_reviewed,
            "reviewer_id": reviewer_id or rec.get("review_status", {}).get("reviewer_id")
        }

        if fully_reviewed:
            self.transition_state(study_id, StudyLifecycleState.REVIEW_COMPLETED.value,
                                  reason=f"review_completed_by_{reviewer_id or 'expert'}")
            self.transition_state(study_id, StudyLifecycleState.AWAITING_ARCHIVAL.value,
                                  reason="ready_for_archival")
        else:
            self.transition_state(study_id, StudyLifecycleState.UNDER_EXPERT_REVIEW.value,
                                  reason="partial_review_recorded")

        return True, f"Updated review status: complete={fully_reviewed}"

    def archive_study(self, study_id: str, vault_root: Optional[str] = None,
                      verify: bool = True) -> Tuple[bool, str]:
        """Archive completed study outputs from SSD to external PERCIVAL_VAULT."""
        rec = self._ledger.get(study_id)
        if not rec:
            return False, "Study not found"

        v_root = vault_root or self.vault_root
        if not v_root or not os.path.isdir(v_root):
            return False, f"Cannot archive: Data Vault not accessible at {v_root}"

        ws_dir = rec.get("active_workspace_location")
        if not ws_dir or not os.path.isdir(ws_dir):
            return False, f"Active workspace missing: {ws_dir}"

        self.transition_state(study_id, StudyLifecycleState.ARCHIVING.value, reason="archive_started")

        dest_dir = os.path.join(v_root, "studies", study_id)
        os.makedirs(dest_dir, exist_ok=True)
        rec["hdd_archive_location"] = dest_dir

        engine = get_transfer_engine(os.path.join(self.base_dir, "app_data", "transfers"))
        try:
            ok, msg, p_info = engine.transfer_path(
                src=ws_dir,
                dst=dest_dir,
                operation="archive",
                study_id=study_id,
                verify_sha=verify,
                preserve_source=True,
                prefer_clone=False  # Cross-device SSD-to-HDD uses bounded streaming
            )
            if not ok:
                raise IOError(f"Archive transfer failed: {msg}")

            rec["archive_status"] = "archived_and_verified"
            self.transition_state(study_id, StudyLifecycleState.ARCHIVED.value, reason="archive_verified")
            return True, f"Successfully archived and verified study {study_id} to {dest_dir}"
        except Exception as e:
            self.transition_state(study_id, StudyLifecycleState.ARCHIVE_VERIFICATION_FAILED.value, reason=str(e))
            return False, f"Archive failed: {e}"

    def verify_archive(self, study_id: str, vault_root: Optional[str] = None) -> Tuple[bool, str]:
        """Verify readability and checksums of the archived study in the external Vault."""
        rec = self._ledger.get(study_id)
        if not rec:
            return False, "Study not found"

        dest_dir = rec.get("hdd_archive_location")
        if not dest_dir or not os.path.isdir(dest_dir):
            return False, f"Archive directory does not exist: {dest_dir}"

        stored_checksums = rec.get("checksums", {})
        for rel, expected in stored_checksums.items():
            if not expected:
                continue
            tgt = os.path.join(dest_dir, rel)
            if not os.path.exists(tgt):
                return False, f"Archived file missing: {rel}"
            actual = compute_file_sha256(tgt)
            if actual != expected:
                return False, f"Archived checksum mismatch for {rel}"

        return True, "Archive verified intact"

    def clean_eligible_workspace(self, study_id: str, retain_recent: int = 1,
                                  force: bool = False) -> Tuple[bool, str]:
        """Remove local SSD working copy ONLY IF study is fully archived and verified."""
        rec = self._ledger.get(study_id)
        if not rec:
            return False, "Study not found"

        # Check eligibility: must be ARCHIVED with verified archive status
        if not force:
            if rec.get("state") != StudyLifecycleState.ARCHIVED.value:
                return False, f"Study {study_id} cannot be cleaned from SSD: not yet archived (current state: {rec.get('state')})"
            if rec.get("archive_status") != "archived_and_verified":
                return False, f"Study {study_id} archive is not verified"
            if not rec.get("review_status", {}).get("review_completed"):
                return False, f"Study {study_id} expert review is still pending"

        ws_dir = rec.get("active_workspace_location")
        if ws_dir and os.path.isdir(ws_dir):
            shutil.rmtree(ws_dir, ignore_errors=True)
            rec["active_workspace_location"] = ""
            rec["last_successful_operation"] = "local_workspace_cleaned_after_archive"
            rec["updated_at"] = time.time()
            self._save_ledger()
            return True, f"Cleaned local SSD workspace for archived study {study_id}"

        return True, "No local workspace existed to clean"

    # -------------------------------------------------------------------------
    # Sequential Study-Processing Queue
    # -------------------------------------------------------------------------
    def enqueue_study(self, study_id: str, priority: int = 0) -> Dict[str, Any]:
        """Add a study to the sequential 1-by-1 processing queue."""
        if study_id not in self._ledger:
            self.register_study(study_id, "")

        for item in self._queue:
            if item.get("study_id") == study_id:
                return {"ok": True, "already_queued": True, "queue_item": item}

        item = {
            "queue_id": f"q_{hashlib.sha256(f'{study_id}_{time.time()}'.encode()).hexdigest()[:8]}",
            "study_id": study_id,
            "status": "pending",
            "priority": priority,
            "staged": False,
            "processed": False,
            "reviewed": False,
            "archived": False,
            "enqueued_at": time.time(),
            "updated_at": time.time()
        }
        self._queue.append(item)
        self._save_queue()
        return {"ok": True, "already_queued": False, "queue_item": item}

    def get_queue(self) -> List[Dict[str, Any]]:
        # Refresh current states from ledger
        for item in self._queue:
            sid = item.get("study_id")
            if sid in self._ledger:
                rec = self._ledger[sid]
                item["state"] = rec.get("state")
                item["review_status"] = rec.get("review_status", {})
                item["archive_status"] = rec.get("archive_status")
                item["estimated_space_mb"] = rec.get("estimated_space_mb", 0.0)
        return list(self._queue)

    def process_next_in_queue(self) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Fetch the next pending study in the queue for staging and processing."""
        pending = [q for q in self._queue if q.get("status") in ("pending", "staged")]
        if not pending:
            return False, "Queue is empty or all studies completed", None

        # Sort by priority desc, enqueued_at asc
        pending.sort(key=lambda x: (-x.get("priority", 0), x.get("enqueued_at", 0)))
        current = pending[0]
        sid = current["study_id"]
        current["status"] = "in_progress"
        current["updated_at"] = time.time()
        self._save_queue()

        return True, f"Active study: {sid}", current

    def complete_queue_item(self, study_id: str) -> None:
        for item in self._queue:
            if item.get("study_id") == study_id:
                item["status"] = "completed"
                item["updated_at"] = time.time()
                break
        self._save_queue()
