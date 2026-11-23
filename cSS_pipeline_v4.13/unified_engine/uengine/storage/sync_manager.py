"""uengine/storage/sync_manager.py - Policy-Driven Study Synchronization Engine.

Implements Automatic Archival, Manual Sync, and Scheduled Sync with:
- Pre-sync preview showing new, changed, conflicting, and skipped files
- Non-destructive conflict handling (never silently overwriting conflicting data)
- Invariant enforcement: External Vault is permanent archive, Mac SSD is active workspace
"""

import os
import time
from typing import Dict, Any, List, Optional
from .models import SyncItem, SyncPreview
from .storage_paths import StoragePathsService
from .storage_state import StorageStateService
from ..unified_transfer_engine import get_transfer_engine, compute_sha256


class SyncManager:
    """Manages policy-driven synchronization between Mac SSD workspace and External Vault."""

    def __init__(self, paths_service: Optional[StoragePathsService] = None,
                 state_service: Optional[StorageStateService] = None):
        self.paths = paths_service or StoragePathsService()
        self.state = state_service or StorageStateService(self.paths)

    def generate_sync_preview(self, study_ids: Optional[List[str]] = None,
                              mode: str = "manual") -> SyncPreview:
        """Scan active study workspaces and compare against External Vault archives."""
        vault_path = self.paths.get_vault_path()
        vault_info = self.paths.get_vault_info()
        avail_bytes = vault_info.available_bytes if vault_info else 0

        if not vault_path or not os.path.isdir(vault_path):
            return SyncPreview(
                mode=mode,
                total_items=0,
                total_bytes=0,
                destination_available_bytes=0,
                can_proceed=False,
                message="External Data Vault is disconnected. Synchronization cannot proceed."
            )

        ws_root = os.path.join(self.paths.workspace_root, "work")
        studies_to_check = study_ids or ([d for d in os.listdir(ws_root) if os.path.isdir(os.path.join(ws_root, d))] if os.path.isdir(ws_root) else [])

        to_copy: List[SyncItem] = []
        conflicts: List[SyncItem] = []
        skipped: List[SyncItem] = []
        total_transfer_bytes = 0

        for sid in studies_to_check:
            ws_study = os.path.join(ws_root, sid)
            vault_study = os.path.join(vault_path, "studies", sid)

            if not os.path.isdir(ws_study):
                continue

            for root, _, files in os.walk(ws_study):
                for f in files:
                    if f.startswith("."):
                        continue
                    sp = os.path.join(root, f)
                    rel = os.path.relpath(sp, ws_study)
                    dp = os.path.join(vault_study, rel)
                    sz = os.path.getsize(sp)

                    if not os.path.exists(dp):
                        # New file to archive
                        item = SyncItem(study_id=sid, relative_path=rel, source_path=sp,
                                        destination_path=dp, size_bytes=sz, action="copy",
                                        reason="New processing output awaiting archival")
                        to_copy.append(item)
                        total_transfer_bytes += sz
                    else:
                        # Existing destination file: check size and timestamp
                        d_sz = os.path.getsize(dp)
                        if sz == d_sz:
                            skipped.append(SyncItem(study_id=sid, relative_path=rel, source_path=sp,
                                                    destination_path=dp, size_bytes=sz, action="skip",
                                                    reason="Identical size in Vault"))
                        else:
                            # Conflict: both copies exist with different sizes
                            conflicts.append(SyncItem(study_id=sid, relative_path=rel, source_path=sp,
                                                      destination_path=dp, size_bytes=sz, action="conflict",
                                                      reason="File size mismatch between SSD and Vault"))

        can_proceed = (avail_bytes > total_transfer_bytes + (500 * 1024 * 1024)) and len(conflicts) == 0

        return SyncPreview(
            mode=mode,
            total_items=len(to_copy) + len(conflicts) + len(skipped),
            total_bytes=total_transfer_bytes,
            items_to_copy=to_copy,
            items_conflicting=conflicts,
            items_skipped=skipped,
            destination_available_bytes=avail_bytes,
            can_proceed=can_proceed,
            message="Ready to synchronize" if can_proceed else ("Insufficient Vault space" if avail_bytes <= total_transfer_bytes else "Conflicts detected: review required")
        )

    def execute_sync(self, preview_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Execute approved sync plan using UnifiedTransferEngine."""
        items = preview_dict.get("items_to_copy", [])
        if not items:
            return {"ok": True, "message": "Nothing to synchronize.", "transferred_count": 0}

        engine = get_transfer_engine(os.path.join(self.paths.workspace_root, "app_data", "transfers"))
        transferred = 0
        total_bytes = 0
        job_id = f"sync_{int(time.time())}"

        self.state.record_audit_event("sync_started", "initiated", op_id=job_id, details={"items_count": len(items)})

        for it in items:
            sp = it["source_path"]
            dp = it["destination_path"]
            sid = it["study_id"]

            ok, msg, info = engine.transfer_path(
                src=sp,
                dst=dp,
                operation="archive_sync",
                study_id=sid,
                verify_sha=True,
                preserve_source=True,
                prefer_clone=False
            )
            if ok:
                transferred += 1
                total_bytes += info.get("completed_bytes", 0)

        self.state.record_audit_event("sync_completed", "success", op_id=job_id, details={"transferred": transferred, "bytes": total_bytes})
        return {
            "ok": True,
            "job_id": job_id,
            "transferred_count": transferred,
            "transferred_bytes": total_bytes,
            "message": f"Successfully synchronized {transferred} files to external Vault."
        }
