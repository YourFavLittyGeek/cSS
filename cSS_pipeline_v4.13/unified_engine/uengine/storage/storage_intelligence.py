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

    def get_detailed_storage_metrics(self) -> Dict[str, Any]:
        """Calculate authoritative, granular storage metrics for Mac SSD and External Vault."""
        import time
        import shutil

        def get_dir_size(d: str) -> int:
            if not d or not os.path.isdir(d):
                return 0
            sz = 0
            try:
                for root, _, files in os.walk(d):
                    for f in files:
                        try:
                            sz += os.path.getsize(os.path.join(root, f))
                        except Exception:
                            pass
            except Exception:
                pass
            return sz

        # Internal SSD metrics
        ws_root = self.paths.workspace_root
        ssd_usage = shutil.disk_usage(ws_root)
        total_ssd = ssd_usage.total
        free_ssd = ssd_usage.free
        used_ssd = ssd_usage.used

        active_ws_sz = get_dir_size(os.path.join(ws_root, "work")) + get_dir_size(os.path.join(ws_root, "subjects"))
        scratch_sz = get_dir_size(os.path.join(ws_root, "app_data", "scratch")) + get_dir_size(os.path.join(ws_root, "app_data", "staging"))
        app_data_sz = get_dir_size(os.path.join(ws_root, "app_data"))
        pensieve_file = os.path.join(ws_root, "app_data", "pensieve.db")
        pensieve_sz = os.path.getsize(pensieve_file) if os.path.isfile(pensieve_file) else 0
        quarantine_sz = get_dir_size(os.path.join(ws_root, "app_data", "quarantine")) + get_dir_size(os.path.join(ws_root, "app_data", "transfers", "quarantine"))
        raw_pres_sz = get_dir_size(os.path.join(ws_root, "raw", "import_source_preserved")) + get_dir_size(os.path.join(ws_root, "app_data", "import_src"))

        percival_ssd_managed = active_ws_sz + scratch_sz + app_data_sz + quarantine_sz + raw_pres_sz

        ssd_metrics = {
            "volume_name": "Macintosh HD (NVMe SSD)",
            "mount_path": ws_root,
            "total_bytes": total_ssd,
            "total_gb": round(total_ssd / (1024**3), 2),
            "used_bytes": used_ssd,
            "used_gb": round(used_ssd / (1024**3), 2),
            "free_bytes": free_ssd,
            "free_gb": round(free_ssd / (1024**3), 2),
            "free_pct": round((free_ssd / total_ssd * 100.0) if total_ssd > 0 else 0.0, 1),
            "active_workspace_bytes": active_ws_sz,
            "active_workspace_gb": round(active_ws_sz / (1024**3), 3),
            "temporary_scratch_bytes": scratch_sz,
            "temporary_scratch_mb": round(scratch_sz / (1024**2), 1),
            "app_data_bytes": app_data_sz,
            "pensieve_database_bytes": pensieve_sz,
            "pensieve_database_mb": round(pensieve_sz / (1024**2), 2),
            "quarantined_bytes": quarantine_sz,
            "preserved_raw_bytes": raw_pres_sz,
            "percival_managed_bytes": percival_ssd_managed,
            "percival_managed_gb": round(percival_ssd_managed / (1024**3), 2),
            "measurement_status": "measured",
            "timestamp": time.time()
        }

        # External Vault metrics
        vault_info = self.paths.get_vault_info()
        vault_path = self.paths.get_vault_path()

        if vault_info and vault_info.is_connected and vault_path and os.path.isdir(vault_path):
            v_usage = shutil.disk_usage(vault_path)
            v_total = v_usage.total
            v_free = v_usage.free
            v_used = v_usage.used

            v_archive_sz = get_dir_size(os.path.join(vault_path, "studies"))
            v_orig_mri_sz = get_dir_size(os.path.join(vault_path, "original_mri")) + get_dir_size("/Volumes/Percival/Dicom")
            v_backup_sz = get_dir_size(os.path.join(vault_path, "pensieve_backups"))
            v_quarantine_sz = get_dir_size(os.path.join(vault_path, "quarantine"))
            v_managed = v_archive_sz + v_orig_mri_sz + v_backup_sz + v_quarantine_sz
            v_unregistered = max(0, v_used - v_managed)

            vault_metrics = {
                "connected": True,
                "volume_name": vault_info.volume_name or "Percival Vault HDD",
                "volume_uuid": vault_info.volume_uuid or "EXTERNAL_VAULT",
                "filesystem": vault_info.filesystem or "ExFAT/APFS",
                "mount_path": vault_path,
                "total_bytes": v_total,
                "total_gb": round(v_total / (1024**3), 2),
                "used_bytes": v_used,
                "used_gb": round(v_used / (1024**3), 2),
                "free_bytes": v_free,
                "free_gb": round(v_free / (1024**3), 2),
                "free_pct": round((v_free / v_total * 100.0) if v_total > 0 else 0.0, 1),
                "percival_managed_bytes": v_managed,
                "percival_managed_gb": round(v_managed / (1024**3), 2),
                "original_mri_archive_bytes": v_orig_mri_sz,
                "original_mri_archive_gb": round(v_orig_mri_sz / (1024**3), 2),
                "verified_archive_bytes": v_archive_sz,
                "verified_archive_gb": round(v_archive_sz / (1024**3), 2),
                "pensieve_backup_bytes": v_backup_sz,
                "pensieve_backup_mb": round(v_backup_sz / (1024**2), 2),
                "quarantined_bytes": v_quarantine_sz,
                "unregistered_bytes": v_unregistered,
                "unregistered_gb": round(v_unregistered / (1024**3), 2),
                "measurement_status": "measured",
                "timestamp": time.time()
            }
        else:
            vault_metrics = {
                "connected": False,
                "volume_name": "External Vault HDD",
                "volume_uuid": "NOT_DETECTED",
                "filesystem": "Unavailable",
                "mount_path": vault_path or "Not configured",
                "total_bytes": 0,
                "total_gb": 0,
                "used_bytes": 0,
                "used_gb": 0,
                "free_bytes": 0,
                "free_gb": 0,
                "free_pct": 0,
                "percival_managed_bytes": 0,
                "percival_managed_gb": 0,
                "original_mri_archive_bytes": 0,
                "verified_archive_bytes": 0,
                "pensieve_backup_bytes": 0,
                "quarantined_bytes": 0,
                "unregistered_bytes": 0,
                "measurement_status": "unavailable",
                "timestamp": time.time()
            }

        return {
            "ok": True,
            "mac_internal": ssd_metrics,
            "external_vault": vault_metrics,
            "timestamp": time.time()
        }
