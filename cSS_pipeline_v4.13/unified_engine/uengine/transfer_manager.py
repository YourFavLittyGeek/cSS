"""uengine/transfer_manager.py - Automatic Transfer, Staging & Migration Manager for PERCIVAL.

Manages durable copy/move transfers from Mac internal NVMe SSD to External Data Vault with:
- SHA-256 pre/post transfer verification before source removal
- Category-specific transfer policies
- Persistent JSON-backed transfer queue
- Disconnection fault tolerance & automatic resume
- 'Free Up Mac Space' audit and execution
"""

import os
import json
import time
import shutil
import hashlib
from typing import Dict, Any, List, Optional
from .unified_transfer_engine import get_transfer_engine


TRANSFER_CATEGORIES = [
    {"id": "original_mri", "name": "Original MRI Scans", "default_policy": "copy_to_vault"},
    {"id": "imported_mri", "name": "Imported Staged MRI", "default_policy": "copy_to_vault"},
    {"id": "processed_mri", "name": "Processed MRI (Cortical Surfaces)", "default_policy": "archive_after_processing"},
    {"id": "albus_outputs", "name": "ALBUS Geometric Detections", "default_policy": "archive_after_processing"},
    {"id": "lumos_outputs", "name": "LUMOS Neural Inferences", "default_policy": "archive_after_processing"},
    {"id": "nox_outputs", "name": "NOX Epistemic Maps", "default_policy": "archive_after_processing"},
    {"id": "expert_annotations", "name": "Expert Radiologist Annotations", "default_policy": "copy_to_vault"},
    {"id": "pensieve_backups", "name": "Pensieve Core Memory Backups", "default_policy": "copy_to_vault"},
    {"id": "training_datasets", "name": "Training Datasets & Manifests", "default_policy": "copy_to_vault"},
    {"id": "model_checkpoints", "name": "Model Checkpoints", "default_policy": "copy_to_vault"},
    {"id": "reports_exports", "name": "Clinical Reports & Excel Exports", "default_policy": "copy_to_vault"},
    {"id": "logs", "name": "Diagnostic Logs", "default_policy": "archive_after_30_days"},
    {"id": "temporary_files", "name": "Scratch & Temporary Files", "default_policy": "keep_on_mac"},
]


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


class TransferManager:
    def __init__(self, base_dir: str, vault_root: Optional[str] = None):
        self.base_dir = os.path.abspath(base_dir)
        self.vault_root = os.path.abspath(vault_root) if vault_root else None
        self.app_data_dir = os.path.join(self.base_dir, "app_data")
        self.queue_file = os.path.join(self.app_data_dir, "transfer_queue.json")
        self.policy_file = os.path.join(self.app_data_dir, "transfer_policies.json")
        os.makedirs(self.app_data_dir, exist_ok=True)
        self._ensure_files()

    def _ensure_files(self) -> None:
        if not os.path.exists(self.queue_file):
            with open(self.queue_file, "w") as f:
                json.dump([], f)
        if not os.path.exists(self.policy_file):
            default_policies = {c["id"]: c["default_policy"] for c in TRANSFER_CATEGORIES}
            default_policies["auto_schedule"] = "on_vault_connect"
            default_policies["remove_local_original_after_verify"] = False
            with open(self.policy_file, "w") as f:
                json.dump(default_policies, f, indent=2)

    def get_policies(self) -> Dict[str, Any]:
        try:
            with open(self.policy_file, "r") as f:
                return json.load(f)
        except Exception:
            return {c["id"]: c["default_policy"] for c in TRANSFER_CATEGORIES}

    def update_policies(self, policies: Dict[str, Any]) -> Dict[str, Any]:
        cur = self.get_policies()
        cur.update(policies)
        tmp = self.policy_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cur, f, indent=2)
        os.replace(tmp, self.policy_file)
        return {"ok": True, "policies": cur}

    def _load_queue(self) -> List[Dict[str, Any]]:
        try:
            with open(self.queue_file, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_queue(self, queue: List[Dict[str, Any]]) -> None:
        tmp = self.queue_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(queue, f, indent=2)
        os.replace(tmp, self.queue_file)

    def get_queue(self) -> List[Dict[str, Any]]:
        return self._load_queue()[::-1]

    def enqueue_study(self, study_code: str, action: str = "archive") -> Dict[str, Any]:
        """Enqueue an entire study for verified transfer to Data Vault."""
        q = self._load_queue()
        job_id = f"job_{study_code}_{int(time.time())}"

        # Find files for study
        src_files = []
        review_file = os.path.join(self.base_dir, "review", f"{study_code}_candidates.csv")
        if os.path.isfile(review_file):
            src_files.append(review_file)
        subj_dir = os.path.join(self.base_dir, "subjects", study_code)
        if os.path.isdir(subj_dir):
            for root, _, files in os.walk(subj_dir):
                for f in files:
                    src_files.append(os.path.join(root, f))

        total_bytes = sum(os.path.getsize(f) for f in src_files if os.path.isfile(f))

        entry = {
            "job_id": job_id,
            "study_code": study_code,
            "action": action,
            "total_files": len(src_files),
            "total_bytes": total_bytes,
            "transferred_bytes": 0,
            "progress_pct": 0,
            "status": "pending",  # pending, transferring, completed, paused, failed
            "enqueued_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "completed_at": None,
            "error": None,
            "retries": 0,
        }
        q.append(entry)
        self._save_queue(q)
        return {"ok": True, "job": entry}

    def process_next(self) -> Dict[str, Any]:
        """Process next pending job in queue with strict checksum verification."""
        if not self.vault_root or not os.path.exists(self.vault_root):
            return {"ok": False, "error": "External Data Vault is disconnected"}

        q = self._load_queue()
        pending = [j for j in q if j["status"] == "pending"]
        if not pending:
            return {"ok": True, "message": "Queue is empty"}

        job = pending[0]
        job["status"] = "transferring"
        self._save_queue(q)

        code = job["study_code"]
        target_vault_dir = os.path.join(self.vault_root, "Processed_MRI", code)
        os.makedirs(target_vault_dir, exist_ok=True)

        try:
            # Phase 1b: one verified, study-locked, all-or-nothing, write-once archive job (an archived file with different
            # content is a conflict: nothing is written and the queue item fails with the reason)
            from .transfer.service import TransferService
            pairs = []
            rev_file = os.path.join(self.base_dir, "review", f"{code}_candidates.csv")
            if os.path.isfile(rev_file):
                pairs.append((rev_file, os.path.join(self.vault_root, "Candidates", "ALBUS", f"{code}_candidates.csv")))
            subj_dir = os.path.join(self.base_dir, "subjects", code)
            if os.path.isdir(subj_dir):
                pairs.append((subj_dir, target_vault_dir))
            if pairs:
                svc = TransferService(self.base_dir, self.vault_root)
                try:
                    rep = svc.transfer("archive", pairs, study_id=code)
                finally:
                    svc.close()
                if not rep["ok"]:
                    raise IOError(f"archive job {rep['job_id']} ended {rep['state']}: {'; '.join(rep['errors'])}")
                job["transfer_job_id"] = rep["job_id"]
                job["transferred_bytes"] = sum(os.path.getsize(p) for p in rep["committed"] if os.path.isfile(p))

            job["status"] = "completed"
            job["progress_pct"] = 100.0
            job["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save_queue(q)
            return {"ok": True, "job_id": job["job_id"], "status": "completed"}
        except Exception as e:
            job["status"] = "failed"
            job["error"] = str(e)
            job["retries"] += 1
            self._save_queue(q)
            return {"ok": False, "error": str(e)}

    def free_up_mac_space_preview(self) -> Dict[str, Any]:
        """Audit studies and directories that have verified Data Vault copies and can be safely reclaimed."""
        reclaimable_items: List[Dict[str, Any]] = []
        total_reclaimable_bytes = 0

        # Check local staging
        stg_dir = os.path.join(self.base_dir, "app_data", "staging")
        if os.path.isdir(stg_dir):
            for entry in os.listdir(stg_dir):
                sp = os.path.join(stg_dir, entry)
                if os.path.isdir(sp):
                    sz = sum(os.lstat(os.path.join(r, f)).st_size for r, _, fs in os.walk(sp) for f in fs)   # lstat: staging holds LINKS to the import copies
                    total_reclaimable_bytes += sz
                    reclaimable_items.append({
                        "name": f"Staging Buffer: {entry}",
                        "category": "staging",
                        "study_code": entry,
                        "path": sp,
                        "size_bytes": sz,
                        "size_mb": round(sz / (1024**2), 1),
                        "safe_to_clean": True,
                        "reason": "Staging buffers can be cleanly re-extracted from source"
                    })

        # Check scratch
        scratch_dir = os.path.join(self.base_dir, "app_data", "scratch")
        if os.path.isdir(scratch_dir):
            sz = sum(os.lstat(os.path.join(r, f)).st_size for r, _, fs in os.walk(scratch_dir) for f in fs)
            if sz > 0:
                total_reclaimable_bytes += sz
                reclaimable_items.append({
                    "name": "Temporary Processing Scratch",
                    "category": "scratch",
                    "study_code": "all",
                    "path": scratch_dir,
                    "size_bytes": sz,
                    "size_mb": round(sz / (1024**2), 1),
                    "safe_to_clean": True,
                    "reason": "Temporary intermediate resampling matrices"
                })

        return {
            "ok": True,
            "vault_connected": bool(self.vault_root and os.path.exists(self.vault_root)),
            "total_reclaimable_mb": round(total_reclaimable_bytes / (1024**2), 1),
            "total_reclaimable_gb": round(total_reclaimable_bytes / (1024**3), 2),
            "items": reclaimable_items
        }

    def execute_free_up_mac_space(self, skip_codes=()) -> Dict[str, Any]:
        """remove staging link folders and scratch (both rebuilt when needed); never a study that is being processed"""
        preview = self.free_up_mac_space_preview()
        reclaimed_bytes = 0
        cleaned_count = 0
        skip_codes = set(skip_codes or ())

        for it in preview.get("items", []):
            p = it["path"]
            if it.get("category") == "staging" and it.get("study_code") in skip_codes:
                continue                                             # a running study still reads its staging links
            if os.path.isdir(p):
                try:
                    sz = it["size_bytes"]
                    shutil.rmtree(p)
                    os.makedirs(p, exist_ok=True)
                    reclaimed_bytes += sz
                    cleaned_count += 1
                except Exception:
                    pass

        return {
            "ok": True,
            "items_cleaned": cleaned_count,
            "reclaimed_mb": round(reclaimed_bytes / (1024**2), 1),
            "reclaimed_gb": round(reclaimed_bytes / (1024**3), 2)
        }
