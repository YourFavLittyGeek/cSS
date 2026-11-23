"""uengine/storage/storage_intelligence.py - Storage Intelligence & Classification Service.

Analyzes data locations, classifies files into scientific categories, identifies cleanup
and synchronization candidates, and enforces safety invariants.
"""

import os
import glob
from typing import Dict, Any, List, Optional
from .models import StorageCategory, StudyStorageState
from .storage_paths import StoragePathsService


class StorageIntelligence:
    """Storage classification, policy intelligence, and eligibility engine."""

    def __init__(self, paths_service: Optional[StoragePathsService] = None):
        self.paths = paths_service or StoragePathsService()

    def classify_path(self, path: str) -> StorageCategory:
        """Classify a file or directory path into one of the 16 standard storage categories."""
        abs_p = os.path.abspath(path)
        p_lower = abs_p.lower()
        base = os.path.basename(abs_p).lower()

        if "/original_mri" in p_lower or "/dicom" in p_lower or "/zip" in p_lower or "import_source_preserved" in p_lower:
            return StorageCategory.ORIGINAL_MRI
        if "/app_data/import_src" in p_lower:
            return StorageCategory.IMPORTED_SOURCE
        if "/app_data/staging" in p_lower:
            return StorageCategory.TEMPORARY_STAGING
        if "/app_data/scratch" in p_lower:
            return StorageCategory.PROCESSING_CACHE
        if "candidates" in base:
            return StorageCategory.ALBUS_CANDIDATES
        if "lumos" in base:
            return StorageCategory.LUMOS_OUTPUTS
        if "nox" in base:
            return StorageCategory.NOX_OUTPUTS
        if "score" in base or "results" in p_lower:
            return StorageCategory.PERCIVAL_RESULTS
        if "annotations" in p_lower or "expert" in base:
            return StorageCategory.EXPERT_ANNOTATIONS
        if base.endswith(".db") and "pensieve" in base:
            if "/vault" in p_lower:
                return StorageCategory.PENSIEVE_BACKUP
            return StorageCategory.PENSIEVE_DATABASE
        if "/models" in p_lower or base.endswith(".pth") or base.endswith(".onnx"):
            return StorageCategory.MODELS_CHECKPOINTS
        if "/logs" in p_lower or base.endswith(".log"):
            return StorageCategory.LOGS_DIAGNOSTICS
        if base.endswith((".docx", ".xlsx", ".pdf")):
            return StorageCategory.RESEARCH_DOCUMENTS
        if "/work" in p_lower:
            return StorageCategory.ACTIVE_WORKSPACE
        if base.endswith((".nii", ".nii.gz", ".dcm", ".ima")):
            return StorageCategory.PROCESSED_MRI

        return StorageCategory.UNKNOWN

    def evaluate_cleanup_eligibility(self, study_id: str, study_record: Dict[str, Any]) -> Dict[str, Any]:
        """Check if a study's local SSD workspace is strictly eligible for safe cleanup."""
        # Rule 1: Original MRI must NEVER be deleted
        # Rule 2: Study must be ARCHIVED and VERIFIED with SHA-256
        # Rule 3: Expert review must be completed
        # Rule 4: Archive files must exist and be readable in Vault

        archive_status = study_record.get("archive_status", "")
        review_status = study_record.get("review_status", {})
        review_done = review_status.get("review_completed", False) if isinstance(review_status, dict) else False

        vault_path = self.paths.get_vault_path()
        if not vault_path:
            return {
                "study_id": study_id,
                "eligible": False,
                "reason": "Data Vault is disconnected. Archival verification cannot be confirmed."
            }

        archive_dir = os.path.join(vault_path, "studies", study_id)
        if not os.path.isdir(archive_dir):
            return {
                "study_id": study_id,
                "eligible": False,
                "reason": f"Archived files do not exist in Data Vault: {archive_dir}"
            }

        if archive_status != "archived_and_verified":
            return {
                "study_id": study_id,
                "eligible": False,
                "reason": f"Study archive status is '{archive_status}', must be 'archived_and_verified'"
            }

        if not review_done:
            return {
                "study_id": study_id,
                "eligible": False,
                "reason": "Expert radiologist review is not complete. Ground truth must be recorded before cleaning."
            }

        ws_dir = os.path.join(self.paths.workspace_root, "work", study_id)
        sz = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(ws_dir) for f in fs) if os.path.isdir(ws_dir) else 0

        return {
            "study_id": study_id,
            "eligible": True,
            "reclaimable_bytes": sz,
            "reclaimable_mb": round(sz / (1024**2), 1),
            "workspace_path": ws_dir,
            "vault_path": archive_dir,
            "reason": "Study is verified in external Vault and expert review is complete."
        }
