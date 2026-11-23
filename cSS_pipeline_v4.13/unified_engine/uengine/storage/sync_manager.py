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
from ..safety import SafetyError, canon, inside, parse_study_codes, validate_study_code


def _valid_code(c: str) -> bool:
    try:
        validate_study_code(c)
        return True
    except SafetyError:
        return False


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
        study_ids = parse_study_codes(study_ids)          # Phase 0: a comma string from the query is no longer iterated per character
        studies_to_check = study_ids or ([d for d in os.listdir(ws_root) if os.path.isdir(os.path.join(ws_root, d)) and _valid_code(d)] if os.path.isdir(ws_root) else [])

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
        """Execute an approved sync plan using UnifiedTransferEngine.

        Phase 0: the posted preview is only a SELECTION. The server recomputes the plan for the selected studies and
        copies only items of its own plan (work/<study>/<rel> -> <vault>/studies/<study>/<rel>, new files only). Any
        posted item that is not in the server's plan - including any client-supplied source or destination path -
        refuses the whole request before anything is copied. Failures are reported (ok=False), never hidden."""
        items = (preview_dict or {}).get("items_to_copy", []) if isinstance(preview_dict, dict) else []
        if not items:
            return {"ok": True, "message": "Nothing to synchronize.", "transferred_count": 0}
        try:
            requested = []
            for it in items:
                sid = validate_study_code(it.get("study_id"))
                rel = it.get("relative_path")
                if not isinstance(rel, str) or not rel or os.path.isabs(rel) or ".." in rel.split(os.sep):
                    raise SafetyError(f"invalid relative path {rel!r}")
                requested.append((sid, rel, it.get("source_path"), it.get("destination_path")))
        except (SafetyError, AttributeError, TypeError) as e:
            return {"ok": False, "error": f"Refused: {e}", "transferred_count": 0}

        fresh = self.generate_sync_preview(study_ids=sorted({r[0] for r in requested}), mode="manual")
        if not fresh.can_proceed:
            return {"ok": False, "error": f"Refused: {fresh.message}", "transferred_count": 0}
        plan = {(i.study_id, i.relative_path): i for i in fresh.items_to_copy}
        rejected = []
        for sid, rel, sp, dp in requested:
            srv = plan.get((sid, rel))
            if srv is None:
                rejected.append({"study_id": sid, "relative_path": rel, "reason": "not in the server's current sync plan"})
            elif (sp is not None and canon(sp) != canon(srv.source_path)) or (dp is not None and canon(dp) != canon(srv.destination_path)):
                rejected.append({"study_id": sid, "relative_path": rel, "reason": "client-supplied path differs from the server's plan"})
        if rejected:
            return {"ok": False, "error": f"Refused: {len(rejected)} item(s) are not part of the server's sync plan; nothing was copied",
                    "rejected": rejected[:50], "transferred_count": 0}

        ws_root = canon(os.path.join(self.paths.workspace_root, "work"))
        vault_studies = canon(os.path.join(self.paths.get_vault_path(), "studies"))
        transferred, total_bytes, failed = 0, 0, []
        job_id = f"sync_{int(time.time())}"
        self.state.record_audit_event("sync_started", "initiated", op_id=job_id, details={"items_count": len(requested)})

        pairs = []
        for sid, rel, _, _ in requested:
            it = plan[(sid, rel)]
            sp, dp = canon(it.source_path), canon(it.destination_path)
            if not inside(sp, os.path.join(ws_root, sid)) or not inside(dp, os.path.join(vault_studies, sid)):
                failed.append({"study_id": sid, "relative_path": rel, "error": "path outside work/<study> or <vault>/studies/<study>"})
            else:
                pairs.append((sp, dp))
        if pairs and not failed:
            # Phase 1b: one verified, all-or-nothing, write-once job (a destination that appeared since the preview is a
            # conflict: nothing is overwritten and nothing of this sync is committed)
            from ..transfer.service import TransferService, TransferRefused
            try:
                svc = TransferService(self.paths.workspace_root, self.paths.get_vault_path())
                try:
                    job = svc.transfer("sync", pairs, study_id=requested[0][0] if len({r[0] for r in requested}) == 1 else None)
                finally:
                    svc.close()
                job_id = job["job_id"]
                if job["ok"]:
                    transferred = len(job["committed"]) + len(job["skipped_identical"])
                    total_bytes = sum(os.path.getsize(p) for p in job["committed"] if os.path.isfile(p))
                else:
                    failed.append({"error": f"sync job {job['job_id']} ended {job['state']}: {'; '.join(job['errors'])}",
                                   "conflicts": job["conflicts"]})
            except TransferRefused as e:
                failed.append({"error": f"Refused: {e}"})

        self.state.record_audit_event("sync_completed", "success" if not failed else "failure", op_id=job_id,
                                      details={"transferred": transferred, "bytes": total_bytes, "failed": len(failed)})
        return {
            "ok": not failed,
            "job_id": job_id,
            "transferred_count": transferred,
            "transferred_bytes": total_bytes,
            "failed_count": len(failed),
            "failed": failed[:50],
            "message": (f"Successfully synchronized {transferred} files to external Vault." if not failed
                        else f"{transferred} file(s) synchronized, {len(failed)} failed."),
            **({} if not failed else {"error": f"{len(failed)} file(s) failed to synchronize"}),
        }

    def get_sync_policy(self) -> Dict[str, Any]:
        """Load persistent synchronization policy and category configurations."""
        import json
        policy_file = os.path.join(self.paths.workspace_root, "app_data", "transfers", "sync_policy.json")
        default_policy = {
            "categories": {
                "original_mri": {"enabled": True, "immutable": True, "description": "Original raw MRI datasets (Read-only, immutable permanent archive)"},
                "processed_mri": {"enabled": True, "immutable": False, "description": "Coregistered and skull-stripped MRI volumes"},
                "expert_annotations": {"enabled": True, "immutable": False, "description": "Clinician labels, boundary calls, and confirmed lesions"},
                "reports": {"enabled": True, "immutable": False, "description": "Generated diagnostic sheets, PDF/XLSX summaries"},
                "pensieve": {"enabled": True, "immutable": False, "description": "Pensieve SQLite online verified database snapshots"},
                "scratch": {"enabled": False, "immutable": False, "description": "Temporary resampling buffers and intermediate tensors (Excluded)"},
                "caches": {"enabled": False, "immutable": False, "description": "Regenerable viewer tiles and image thumbnails (Excluded)"}
            },
            "auto_triggers": {
                "on_study_completed": True,
                "on_review_completed": True,
                "on_app_idle": False,
                "on_drive_reconnect": True,
                "schedule_interval_minutes": 60
            },
            "conflict_policy": "quarantine", # quarantine, keep_both, ask
            "updated_at": time.time()
        }
        if os.path.isfile(policy_file):
            try:
                with open(policy_file, "r") as f:
                    data = json.load(f)
                    default_policy.update(data)
            except Exception:
                pass
        return default_policy

    def save_sync_policy(self, policy: Dict[str, Any]) -> Dict[str, Any]:
        """Save updated synchronization policy."""
        import json
        policy_file = os.path.join(self.paths.workspace_root, "app_data", "transfers", "sync_policy.json")
        os.makedirs(os.path.dirname(policy_file), exist_ok=True)
        policy["updated_at"] = time.time()
        with open(policy_file + ".tmp", "w") as f:
            json.dump(policy, f, indent=2)
        os.replace(policy_file + ".tmp", policy_file)
        return {"ok": True, "policy": policy}

    def get_sync_overview(self) -> Dict[str, Any]:
        """Compile a high-level summary of synchronization health and pending data."""
        vault_info = self.paths.get_vault_info()
        preview = self.generate_sync_preview(mode="check")
        policy = self.get_sync_policy()

        audit_events = self.state.get_audit_events(limit=5)
        last_sync = next((e for e in audit_events if e.get("action") == "sync_completed"), None)

        return {
            "ok": True,
            "external_connected": vault_info.is_connected if vault_info else False,
            "vault_mount": vault_info.mount_point if vault_info else "None",
            "last_successful_sync": last_sync.get("timestamp") if last_sync else None,
            "next_scheduled_sync": time.time() + (policy.get("auto_triggers", {}).get("schedule_interval_minutes", 60) * 60),
            "pending_items_count": len(preview.items_to_copy),
            "pending_bytes": preview.total_bytes,
            "pending_mb": round(preview.total_bytes / (1024 * 1024), 1),
            "conflicts_count": len(preview.items_conflicting),
            "skipped_count": len(preview.items_skipped),
            "can_proceed": preview.can_proceed,
            "status_message": preview.message,
            "policy": policy
        }
