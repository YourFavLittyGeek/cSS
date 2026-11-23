"""staging.py - Intelligent Mac SSD & External Data Vault staging and archival engine.

Provides controlled high-performance staging from external storage to local Mac SSD
for compute-intensive neuroimaging pipelines, with atomic verified archival and safe cleanup.
"""

import hashlib
import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from .unified_transfer_engine import get_transfer_engine


def compute_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


class StagingManager:
    def __init__(self, base_dir: str, staging_dir: Optional[str] = None):
        self.base_dir = os.path.abspath(base_dir)
        self.staging_dir = os.path.abspath(staging_dir or os.path.join(self.base_dir, "app_data", "staging"))
        os.makedirs(self.staging_dir, exist_ok=True)
        self.journal_file = os.path.join(self.base_dir, "app_data", "staging_journal.json")

    def estimate_staging_space(self, file_paths: List[str], multiplier: float = 3.0) -> Dict[str, Any]:
        """Estimate space needed for staging and subsequent processing expansion (default 3x multiplier)."""
        total_source_bytes = 0
        for p in file_paths:
            if os.path.isfile(p):
                total_source_bytes += os.path.getsize(p)
            elif os.path.isdir(p):
                for root, _, files in os.walk(p):
                    for f in files:
                        fp = os.path.join(root, f)
                        total_source_bytes += os.path.getsize(fp)

        required_bytes = int(total_source_bytes * multiplier)
        usage = shutil.disk_usage(self.staging_dir)
        free_bytes = usage.free
        headroom_bytes = free_bytes - required_bytes
        # Safe headroom requires at least 10 GB remaining after staging and compute
        is_sufficient = headroom_bytes > (10 * (1024**3))

        return {
            "source_bytes": total_source_bytes,
            "source_mb": round(total_source_bytes / (1024**2), 2),
            "required_bytes": required_bytes,
            "required_mb": round(required_bytes / (1024**2), 2),
            "free_bytes": free_bytes,
            "free_mb": round(free_bytes / (1024**2), 2),
            "headroom_mb": round(headroom_bytes / (1024**2), 2),
            "is_sufficient": is_sufficient,
            "warning": None if is_sufficient else f"Insufficient Mac SSD space: requires {required_bytes / (1024**2):.1f} MB with headroom; only {free_bytes / (1024**2):.1f} MB free.",
        }

    def stage_study(self, study_code: str, source_files: List[str], verify: bool = True) -> Dict[str, Any]:
        """Copy input MRI/NIfTI files from external drive or raw source to fast local SSD staging via UnifiedTransferEngine."""
        target_dir = os.path.join(self.staging_dir, study_code)
        os.makedirs(target_dir, exist_ok=True)
        engine = get_transfer_engine(os.path.join(self.base_dir, "app_data", "transfers"))

        staged_files: List[Dict[str, Any]] = []
        for src in source_files:
            if not os.path.exists(src):
                raise FileNotFoundError(f"Source file not found: {src}")

            base_name = os.path.basename(src)
            dest = os.path.join(target_dir, base_name)

            ok, msg, p_info = engine.transfer_path(
                src=src,
                dst=dest,
                operation="stage",
                study_id=study_code,
                verify_sha=verify,
                preserve_source=True,
                prefer_clone=True
            )
            if not ok:
                raise IOError(f"Staging transfer failed for {base_name}: {msg}")

            dest_hash = compute_sha256(dest) if verify else ""
            staged_files.append({
                "source": src,
                "staged": dest,
                "size_bytes": os.path.getsize(dest),
                "checksum": dest_hash,
            })

        result = {
            "study_code": study_code,
            "staging_dir": target_dir,
            "files": staged_files,
            "staged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._record_journal("stage", result)
        return result

    def archive_results(
        self,
        study_code: str,
        output_files: List[str],
        vault_dest_dir: str,
        verify: bool = True,
    ) -> Dict[str, Any]:
        """Atomically transfer completed analysis outputs to external Data Vault via UnifiedTransferEngine."""
        os.makedirs(vault_dest_dir, exist_ok=True)
        engine = get_transfer_engine(os.path.join(self.base_dir, "app_data", "transfers"))
        archived_files: List[Dict[str, Any]] = []

        for src in output_files:
            if not os.path.exists(src):
                continue
            base_name = os.path.basename(src)
            dest = os.path.join(vault_dest_dir, base_name)

            ok, msg, p_info = engine.transfer_path(
                src=src,
                dst=dest,
                operation="archive",
                study_id=study_code,
                verify_sha=verify,
                preserve_source=True,
                prefer_clone=False
            )
            if not ok:
                raise IOError(f"Archival transfer failed for {base_name}: {msg}")

            dest_hash = compute_sha256(dest) if verify else ""
            archived_files.append({
                "local": src,
                "vault": dest,
                "size_bytes": os.path.getsize(dest),
                "checksum": dest_hash,
            })

        result = {
            "study_code": study_code,
            "vault_dir": vault_dest_dir,
            "archived_count": len(archived_files),
            "files": archived_files,
            "archived_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._record_journal("archive", result)
        return result

    def cleanup_staging(self, study_code: str) -> Dict[str, Any]:
        """Remove local staging directory for study after verified archival."""
        target_dir = os.path.join(self.staging_dir, study_code)
        reclaimed_bytes = 0
        if os.path.isdir(target_dir):
            for root, _, files in os.walk(target_dir):
                for f in files:
                    reclaimed_bytes += os.path.getsize(os.path.join(root, f))
            shutil.rmtree(target_dir, ignore_errors=True)

        return {
            "study_code": study_code,
            "cleaned": True,
            "reclaimed_bytes": reclaimed_bytes,
            "reclaimed_mb": round(reclaimed_bytes / (1024**2), 2),
        }

    def prune_local_originals(
        self,
        study_code: str,
        local_files: List[str],
        vault_files: List[str],
        policy_allowed: bool = False,
    ) -> Dict[str, Any]:
        """Optional setting: Remove local original MRI copies ONLY if policy is enabled and vault verified."""
        if not policy_allowed:
            return {
                "study_code": study_code,
                "pruned": False,
                "reason": "Policy 'remove_local_mri_after_archive' is DISABLED (default safe mode). Local originals retained.",
            }

        # Verify 1-to-1 match and identical checksums before removing anything
        if len(local_files) != len(vault_files):
            return {
                "study_code": study_code,
                "pruned": False,
                "reason": f"File count mismatch: {len(local_files)} local vs {len(vault_files)} in vault. Aborting prune.",
            }

        removed_files: List[str] = []
        reclaimed_bytes = 0

        for loc, vlt in zip(local_files, vault_files):
            if not os.path.exists(loc) or not os.path.exists(vlt):
                return {
                    "study_code": study_code,
                    "pruned": False,
                    "reason": f"Missing file pair: {loc} or {vlt}. Aborting prune.",
                }
            loc_hash = compute_sha256(loc)
            vlt_hash = compute_sha256(vlt)
            if loc_hash != vlt_hash:
                return {
                    "study_code": study_code,
                    "pruned": False,
                    "reason": f"Checksum mismatch between local and vault: {loc}. Aborting prune.",
                }

        for loc in local_files:
            sz = os.path.getsize(loc)
            os.remove(loc)
            removed_files.append(loc)
            reclaimed_bytes += sz

        return {
            "study_code": study_code,
            "pruned": True,
            "removed_files": removed_files,
            "reclaimed_bytes": reclaimed_bytes,
            "reclaimed_mb": round(reclaimed_bytes / (1024**2), 2),
        }

    def _record_journal(self, action: str, record: Dict[str, Any]) -> None:
        try:
            journal: List[Dict[str, Any]] = []
            if os.path.exists(self.journal_file):
                try:
                    with open(self.journal_file, "r") as f:
                        journal = json.load(f)
                except Exception:
                    journal = []
            journal.append({"action": action, "timestamp": time.time(), "record": record})
            # Keep last 500 events
            journal = journal[-500:]
            tmp = self.journal_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(journal, f, indent=1)
            os.replace(tmp, self.journal_file)
        except Exception:
            pass
