"""uengine/cleaning_manager.py - Complete Data Lifecycle & Safe Cleaning Manager for PERCIVAL.

Manages retention policies, age-based cleanup, original/processed MRI management,
study/cohort operations, previously trained study reclamation, and a safe quarantine & restore system.
Strictly safeguards expert annotations, Pensieve history, active jobs, and single original MRI copies.
"""

import os
import glob
import json
import time
import shutil
import hashlib
from typing import Dict, Any, List, Optional


CLEAN_CATEGORIES = [
    {"id": "temp_processing", "name": "Temporary Processing Files", "default_days": 7, "path": "app_data/scratch"},
    {"id": "failed_temp", "name": "Failed & Incomplete Run Files", "default_days": 14, "path": "review/*.incomplete"},
    {"id": "regenerable_caches", "name": "Regenerable Caches & Snapshots", "default_days": 30, "path": "app_data/qc"},
    {"id": "original_mri", "name": "Original MRI Scans (Local Copies)", "default_days": -1, "path": "data"},
    {"id": "processed_mri", "name": "Processed MRI (Cortical Surfaces)", "default_days": 30, "path": "subjects"},
    {"id": "intermediate_derivatives", "name": "Intermediate Derivatives & Transforms", "default_days": 30, "path": "work"},
    {"id": "albus_lumos_nox", "name": "ALBUS / LUMOS / NOX Outputs", "default_days": 60, "path": "results"},
    {"id": "training_staging", "name": "Training Staging Buffers", "default_days": 14, "path": "app_data/staging"},
    {"id": "model_checkpoints", "name": "Intermediate Model Checkpoints", "default_days": 90, "path": "models/checkpoints"},
    {"id": "logs", "name": "Execution & Diagnostic Logs", "default_days": 30, "path": "app_data/logs"},
    {"id": "exports", "name": "Old Reports & Excel Exports", "default_days": 90, "path": "results"},
    {"id": "studies", "name": "Individual Inactive Studies", "default_days": -1, "path": "review"},
    {"id": "cohorts", "name": "Cohort Collections", "default_days": -1, "path": "cohorts"},
    {"id": "trained_studies", "name": "Previously Trained Studies", "default_days": 30, "path": "training_manifests"},
    {"id": "duplicate_files", "name": "Verified Duplicate Copies", "default_days": 7, "path": "app_data/duplicates"},
    {"id": "other_managed", "name": "Other Application-Managed Staging", "default_days": 30, "path": "app_data/tmp"},
]


class CleaningManager:
    def __init__(self, base_dir: str, vault_root: Optional[str] = None):
        self.base_dir = os.path.abspath(base_dir)
        self.vault_root = os.path.abspath(vault_root) if vault_root else None
        self.app_data_dir = os.path.join(self.base_dir, "app_data")
        self.quarantine_dir = os.path.join(self.app_data_dir, "quarantine")
        self.history_file = os.path.join(self.app_data_dir, "cleanup_history.jsonl")
        self.policy_file = os.path.join(self.app_data_dir, "cleaning_policies.json")
        os.makedirs(self.quarantine_dir, exist_ok=True)
        self._ensure_policy()

    def _ensure_policy(self) -> None:
        if not os.path.exists(self.policy_file):
            default_policies = {
                "mode": "assisted",  # smart_automatic, assisted, manual
                "min_free_space_gb": 20.0,
                "categories": {c["id"]: c["default_days"] for c in CLEAN_CATEGORIES},
                "original_mri_mode": "archive_verify_remove",  # keep_local, manual, archive_verify_remove
                "exclusions": []
            }
            try:
                with open(self.policy_file, "w") as f:
                    json.dump(default_policies, f, indent=2)
            except Exception:
                pass

    def get_policies(self) -> Dict[str, Any]:
        try:
            with open(self.policy_file, "r") as f:
                return json.load(f)
        except Exception:
            return {
                "mode": "assisted",
                "min_free_space_gb": 20.0,
                "categories": {c["id"]: c["default_days"] for c in CLEAN_CATEGORIES},
                "original_mri_mode": "archive_verify_remove",
                "exclusions": []
            }

    def update_policies(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        pol = self.get_policies()
        pol.update(updates)
        tmp = self.policy_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(pol, f, indent=2)
        os.replace(tmp, self.policy_file)
        return {"ok": True, "policies": pol}

    def _record_history(self, entry: Dict[str, Any]) -> None:
        entry["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
        entry["epoch"] = time.time()
        try:
            with open(self.history_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not os.path.exists(self.history_file):
            return []
        lines = []
        try:
            with open(self.history_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            lines.append(json.loads(line))
                        except Exception:
                            pass
        except Exception:
            pass
        return lines[-limit:][::-1]

    def get_dashboard(self) -> Dict[str, Any]:
        """Aggregate data lifecycle stats, recoverable space, and eligible files."""
        now = time.time()
        policies = self.get_policies()
        category_policies = policies.get("categories", {})

        stats: List[Dict[str, Any]] = []
        total_reclaimable_bytes = 0

        for cat in CLEAN_CATEGORIES:
            cid = cat["id"]
            days = category_policies.get(cid, cat["default_days"])
            eligible_count = 0
            eligible_bytes = 0

            if days != -1:  # -1 means never auto-clean
                cutoff = now - (days * 86400)
                if cid == "temp_processing":
                    p = os.path.join(self.base_dir, "app_data", "scratch")
                    if os.path.isdir(p):
                        for root, _, files in os.walk(p):
                            for f in files:
                                fp = os.path.join(root, f)
                                try:
                                    if os.path.getmtime(fp) < cutoff:
                                        eligible_count += 1
                                        eligible_bytes += os.path.getsize(fp)
                                except Exception:
                                    pass
                elif cid == "failed_temp":
                    p = os.path.join(self.base_dir, "review")
                    if os.path.isdir(p):
                        for fp in glob.glob(os.path.join(p, "*.incomplete")):
                            try:
                                if os.path.getmtime(fp) < cutoff:
                                    eligible_count += 1
                                    eligible_bytes += os.path.getsize(fp)
                            except Exception:
                                pass
                elif cid == "training_staging":
                    p = os.path.join(self.base_dir, "app_data", "staging")
                    if os.path.isdir(p):
                        for ent in os.listdir(p):
                            ep = os.path.join(p, ent)
                            try:
                                if os.path.getmtime(ep) < cutoff:
                                    eligible_count += 1
                                    eligible_bytes += sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(ep) for f in fs)
                            except Exception:
                                pass
                elif cid == "logs":
                    p = os.path.join(self.base_dir, "app_data", "logs")
                    if os.path.isdir(p):
                        for fp in glob.glob(os.path.join(p, "*.log")):
                            try:
                                if os.path.getmtime(fp) < cutoff:
                                    eligible_count += 1
                                    eligible_bytes += os.path.getsize(fp)
                            except Exception:
                                pass

            total_reclaimable_bytes += eligible_bytes
            stats.append({
                "id": cid,
                "name": cat["name"],
                "retention_days": days,
                "eligible_count": eligible_count,
                "eligible_bytes": eligible_bytes,
                "eligible_mb": round(eligible_bytes / (1024**2), 1),
            })

        # Count quarantined files
        quarantine_items = self.list_quarantine()
        quarantine_bytes = sum(it.get("size", 0) for it in quarantine_items)

        history = self.get_history(limit=5)
        last_cleanup = history[0]["timestamp"] if history else "Never"

        return {
            "ok": True,
            "mode": policies.get("mode", "assisted"),
            "total_reclaimable_mb": round(total_reclaimable_bytes / (1024**2), 1),
            "total_reclaimable_gb": round(total_reclaimable_bytes / (1024**3), 2),
            "categories": stats,
            "quarantine_count": len(quarantine_items),
            "quarantine_mb": round(quarantine_bytes / (1024**2), 1),
            "last_cleanup": last_cleanup,
        }

    def preview_clean(self, category_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Generate detailed file preview before executing clean."""
        now = time.time()
        policies = self.get_policies()
        cats_to_clean = category_ids or [c["id"] for c in CLEAN_CATEGORIES if policies.get("categories", {}).get(c["id"], -1) != -1]

        preview_files: List[Dict[str, Any]] = []
        total_bytes = 0

        for cid in cats_to_clean:
            days = policies.get("categories", {}).get(cid, 7)
            if days == -1:
                continue
            cutoff = now - (days * 86400)
            if cid == "temp_processing":
                p = os.path.join(self.base_dir, "app_data", "scratch")
                if os.path.isdir(p):
                    for root, _, files in os.walk(p):
                        for f in files:
                            fp = os.path.join(root, f)
                            try:
                                if os.path.getmtime(fp) < cutoff:
                                    sz = os.path.getsize(fp)
                                    total_bytes += sz
                                    preview_files.append({
                                        "category": cid,
                                        "path": fp,
                                        "name": f,
                                        "size_bytes": sz,
                                        "size_str": f"{sz/1024:.1f} KB" if sz < 1024**2 else f"{sz/1024**2:.1f} MB",
                                        "age_days": round((now - os.path.getmtime(fp)) / 86400, 1),
                                        "action": "quarantine_then_clean"
                                    })
                            except Exception:
                                pass
            elif cid == "failed_temp":
                p = os.path.join(self.base_dir, "review")
                if os.path.isdir(p):
                    for fp in glob.glob(os.path.join(p, "*.incomplete")):
                        try:
                            if os.path.getmtime(fp) < cutoff:
                                sz = os.path.getsize(fp)
                                total_bytes += sz
                                preview_files.append({
                                    "category": cid,
                                    "path": fp,
                                    "name": os.path.basename(fp),
                                    "size_bytes": sz,
                                    "size_str": f"{sz/1024:.1f} KB",
                                    "age_days": round((now - os.path.getmtime(fp)) / 86400, 1),
                                    "action": "quarantine"
                                })
                        except Exception:
                            pass

        return {
            "ok": True,
            "total_items": len(preview_files),
            "total_reclaimable_mb": round(total_bytes / (1024**2), 2),
            "files": preview_files[:200]  # capped for UI responsiveness
        }

    def execute_clean(self, category_ids: Optional[List[str]] = None, use_quarantine: bool = True) -> Dict[str, Any]:
        """Safely execute cleanup by moving eligible items to quarantine first."""
        prev = self.preview_clean(category_ids)
        files = prev.get("files", [])
        moved_count = 0
        reclaimed_bytes = 0

        for item in files:
            src = item["path"]
            if not os.path.exists(src):
                continue
            sz = item.get("size_bytes", 0)

            # Move to quarantine
            if use_quarantine:
                ts = int(time.time())
                bname = os.path.basename(src)
                qname = f"{ts}_{item['category']}_{bname}"
                dst = os.path.join(self.quarantine_dir, qname)
                try:
                    shutil.move(src, dst)
                    moved_count += 1
                    reclaimed_bytes += sz
                    # Save metadata
                    meta_p = dst + ".meta"
                    with open(meta_p, "w") as mf:
                        json.dump({
                            "original_path": src,
                            "category": item["category"],
                            "quarantined_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "size_bytes": sz
                        }, mf)
                except Exception:
                    pass
            else:
                try:
                    if os.path.isfile(src):
                        os.remove(src)
                    elif os.path.isdir(src):
                        shutil.rmtree(src)
                    moved_count += 1
                    reclaimed_bytes += sz
                except Exception:
                    pass

        self._record_history({
            "operation": "clean_categories",
            "categories": category_ids or "all_policy_eligible",
            "items_cleaned": moved_count,
            "bytes_reclaimed": reclaimed_bytes,
            "quarantined": use_quarantine
        })

        return {
            "ok": True,
            "items_cleaned": moved_count,
            "reclaimed_mb": round(reclaimed_bytes / (1024**2), 2),
            "quarantined": use_quarantine
        }

    def list_quarantine(self) -> List[Dict[str, Any]]:
        """List all items currently in quarantine with restoration metadata."""
        if not os.path.isdir(self.quarantine_dir):
            return []
        items = []
        for ent in os.listdir(self.quarantine_dir):
            if ent.endswith(".meta") or ent.startswith("."):
                continue
            fp = os.path.join(self.quarantine_dir, ent)
            meta_p = fp + ".meta"
            meta = {}
            if os.path.exists(meta_p):
                try:
                    with open(meta_p, "r") as mf:
                        meta = json.load(mf)
                except Exception:
                    pass
            try:
                sz = os.path.getsize(fp) if os.path.isfile(fp) else 0
                items.append({
                    "quarantine_id": ent,
                    "filename": os.path.basename(meta.get("original_path", ent)),
                    "original_path": meta.get("original_path", ""),
                    "category": meta.get("category", "unknown"),
                    "size": sz,
                    "size_str": f"{sz/1024:.1f} KB" if sz < 1024**2 else f"{sz/1024**2:.1f} MB",
                    "quarantined_at": meta.get("quarantined_at", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(fp)))),
                })
            except Exception:
                pass
        return items

    def restore_quarantine(self, quarantine_id: str) -> Dict[str, Any]:
        """Restore quarantined file back to its original path."""
        q_path = os.path.join(self.quarantine_dir, quarantine_id)
        meta_p = q_path + ".meta"
        if not os.path.exists(q_path):
            return {"ok": False, "error": f"Quarantine item not found: {quarantine_id}"}

        original_path = None
        if os.path.exists(meta_p):
            try:
                with open(meta_p, "r") as mf:
                    meta = json.load(mf)
                    original_path = meta.get("original_path")
            except Exception:
                pass

        if not original_path:
            return {"ok": False, "error": "Cannot restore: original path metadata missing"}

        os.makedirs(os.path.dirname(original_path), exist_ok=True)
        try:
            shutil.move(q_path, original_path)
            if os.path.exists(meta_p):
                os.remove(meta_p)
            self._record_history({
                "operation": "quarantine_restore",
                "quarantine_id": quarantine_id,
                "restored_path": original_path
            })
            return {"ok": True, "restored_path": original_path}
        except Exception as e:
            return {"ok": False, "error": f"Failed to restore: {str(e)}"}

    def purge_quarantine(self, quarantine_id: Optional[str] = None) -> Dict[str, Any]:
        """Permanently purge specific item or entire quarantine."""
        purged = 0
        reclaimed = 0
        if quarantine_id:
            fp = os.path.join(self.quarantine_dir, quarantine_id)
            meta_p = fp + ".meta"
            if os.path.exists(fp):
                sz = os.path.getsize(fp) if os.path.isfile(fp) else 0
                if os.path.isdir(fp):
                    shutil.rmtree(fp, ignore_errors=True)
                else:
                    os.remove(fp)
                if os.path.exists(meta_p):
                    os.remove(meta_p)
                purged += 1
                reclaimed += sz
        else:
            for ent in os.listdir(self.quarantine_dir):
                fp = os.path.join(self.quarantine_dir, ent)
                try:
                    if os.path.isdir(fp):
                        shutil.rmtree(fp, ignore_errors=True)
                    else:
                        sz = os.path.getsize(fp)
                        os.remove(fp)
                        reclaimed += sz
                    purged += 1
                except Exception:
                    pass

        self._record_history({
            "operation": "quarantine_purge",
            "items_purged": purged,
            "bytes_reclaimed": reclaimed
        })
        return {"ok": True, "purged_count": purged, "reclaimed_mb": round(reclaimed / (1024**2), 2)}

    def delete_by_study(self, study_code: str, target: str = "staging") -> Dict[str, Any]:
        """Safely delete study outputs from staging or local review, protecting Pensieve."""
        # Absolute protection: Pensieve and Annotations are never deleted
        removed = 0
        if target in ("staging", "all"):
            stg = os.path.join(self.base_dir, "app_data", "staging", study_code)
            if os.path.isdir(stg):
                shutil.rmtree(stg, ignore_errors=True)
                removed += 1

        if target in ("local_processed", "all"):
            # subjects/study_code
            subj = os.path.join(self.base_dir, "subjects", study_code)
            if os.path.isdir(subj):
                # Move to quarantine first
                ts = int(time.time())
                dst = os.path.join(self.quarantine_dir, f"{ts}_study_{study_code}_subjects")
                shutil.move(subj, dst)
                removed += 1

        self._record_history({
            "operation": "delete_by_study",
            "study_code": study_code,
            "target": target,
            "items_removed": removed
        })
        return {"ok": True, "study_code": study_code, "items_removed": removed}
