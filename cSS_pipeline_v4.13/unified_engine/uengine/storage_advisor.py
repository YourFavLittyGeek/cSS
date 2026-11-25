"""storage_advisor.py - Storage intelligence and proactive capacity management for PERCIVAL.

Monitors local Mac SSD and external Data Vault storage capacity, enforces retention policies
(7-day scratch, 14-day failed runs, 30-day logs/cache), and generates space reclamation recommendations.
"""

import glob
import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

TIER_HEALTHY = "HEALTHY"       # > 25% free
TIER_WARNING = "WARNING"       # 20 - 25% free
TIER_CRITICAL = "CRITICAL"     # 10 - 20% free
TIER_EMERGENCY = "EMERGENCY"   # < 10% free


class StorageAdvisor:
    def __init__(self, base_dir: str, vault_mount: Optional[str] = None):
        self.base_dir = os.path.abspath(base_dir)
        self.vault_mount = os.path.abspath(vault_mount) if vault_mount else None
        self.app_data_dir = os.path.join(self.base_dir, "app_data")
        self.scratch_dir = os.path.join(self.app_data_dir, "scratch")
        self.staging_dir = os.path.join(self.app_data_dir, "staging")
        self.logs_dir = os.path.join(self.app_data_dir, "logs")
        self.review_dir = os.path.join(self.base_dir, "review")

    def evaluate_capacity(self, path: Optional[str] = None) -> Dict[str, Any]:
        """Evaluate free disk percentage and assign capacity tier."""
        target = path or self.base_dir
        usage = shutil.disk_usage(target)
        total_gb = usage.total / (1024**3)
        free_gb = usage.free / (1024**3)
        used_gb = usage.used / (1024**3)
        free_pct = (usage.free / usage.total) * 100.0 if usage.total > 0 else 0.0

        if free_pct >= 25.0:
            tier = TIER_HEALTHY
            message = "Storage capacity is healthy."
        elif free_pct >= 20.0:
            tier = TIER_WARNING
            message = "Storage capacity warning: between 20% and 25% free. Consider archiving older runs."
        elif free_pct >= 10.0:
            tier = TIER_CRITICAL
            message = "Storage capacity critical: between 10% and 20% free. Space reclamation recommended."
        else:
            tier = TIER_EMERGENCY
            message = "EMERGENCY: Less than 10% storage free. Automatic staging halted; archive immediately."

        return {
            "path": target,
            "total_gb": round(total_gb, 1),
            "used_gb": round(used_gb, 1),
            "free_gb": round(free_gb, 1),
            "free_percent": round(free_pct, 1),
            "tier": tier,
            "message": message,
        }

    def generate_recommendations(
        self,
        scratch_days: int = 7,
        failed_days: int = 14,
        log_days: int = 30,
    ) -> Dict[str, Any]:
        """Audit storage usage across scratch, staging, failed runs, and logs."""
        now = time.time()
        rec_list: List[Dict[str, Any]] = []
        total_reclaimable_bytes = 0

        # 1. Audit scratch files older than scratch_days
        scratch_bytes = 0
        scratch_files = []
        if os.path.isdir(self.scratch_dir):
            for root, _, files in os.walk(self.scratch_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        mtime = os.path.getmtime(fp)
                        if now - mtime > (scratch_days * 86400):
                            sz = os.path.getsize(fp)
                            scratch_bytes += sz
                            scratch_files.append(fp)
                    except Exception:
                        pass
        if scratch_bytes > 0:
            total_reclaimable_bytes += scratch_bytes
            rec_list.append({
                "action": "prune_scratch",
                "target": "app_data/scratch",
                "days_threshold": scratch_days,
                "file_count": len(scratch_files),
                "reclaimable_bytes": scratch_bytes,
                "reclaimable_mb": round(scratch_bytes / (1024**2), 2),
                "description": f"Delete {len(scratch_files)} temporary scratch files older than {scratch_days} days.",
            })

        # 2. Audit staging files left behind
        staging_bytes = 0
        staging_dirs = []
        if os.path.isdir(self.staging_dir):
            for entry in os.listdir(self.staging_dir):
                ep = os.path.join(self.staging_dir, entry)
                if os.path.isdir(ep):
                    try:
                        mtime = os.path.getmtime(ep)
                        if now - mtime > (3 * 86400):  # Staging older than 3 days
                            sz = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(ep) for f in fs)
                            staging_bytes += sz
                            staging_dirs.append(ep)
                    except Exception:
                        pass
        if staging_bytes > 0:
            total_reclaimable_bytes += staging_bytes
            rec_list.append({
                "action": "prune_staging",
                "target": "app_data/staging",
                "days_threshold": 3,
                "file_count": len(staging_dirs),
                "reclaimable_bytes": staging_bytes,
                "reclaimable_mb": round(staging_bytes / (1024**2), 2),
                "description": f"Clean {len(staging_dirs)} orphan staging directories older than 3 days.",
            })

        # 3. Audit failed run artifacts in review directory
        failed_bytes = 0
        failed_files = []
        if os.path.isdir(self.review_dir):
            for f in glob.glob(os.path.join(self.review_dir, "*.incomplete")):
                try:
                    mtime = os.path.getmtime(f)
                    if now - mtime > (failed_days * 86400):
                        sz = os.path.getsize(f)
                        failed_bytes += sz
                        failed_files.append(f)
                except Exception:
                    pass
        if failed_bytes > 0:
            total_reclaimable_bytes += failed_bytes
            rec_list.append({
                "action": "prune_failed_runs",
                "target": "review/*.incomplete",
                "days_threshold": failed_days,
                "file_count": len(failed_files),
                "reclaimable_bytes": failed_bytes,
                "reclaimable_mb": round(failed_bytes / (1024**2), 2),
                "description": f"Purge {len(failed_files)} incomplete failed run markers older than {failed_days} days.",
            })

        # 4. Audit old log files
        log_bytes = 0
        log_files = []
        if os.path.isdir(self.logs_dir):
            for f in glob.glob(os.path.join(self.logs_dir, "*.log")):
                try:
                    mtime = os.path.getmtime(f)
                    if now - mtime > (log_days * 86400):
                        sz = os.path.getsize(f)
                        log_bytes += sz
                        log_files.append(f)
                except Exception:
                    pass
        if log_bytes > 0:
            total_reclaimable_bytes += log_bytes
            rec_list.append({
                "action": "prune_logs",
                "target": "app_data/logs",
                "days_threshold": log_days,
                "file_count": len(log_files),
                "reclaimable_bytes": log_bytes,
                "reclaimable_mb": round(log_bytes / (1024**2), 2),
                "description": f"Rotate or compress {len(log_files)} log files older than {log_days} days.",
            })

        capacity_info = self.evaluate_capacity()
        return {
            "capacity": capacity_info,
            "total_reclaimable_bytes": total_reclaimable_bytes,
            "total_reclaimable_mb": round(total_reclaimable_bytes / (1024**2), 2),
            "total_reclaimable_gb": round(total_reclaimable_bytes / (1024**3), 2),
            "recommendations": rec_list,
        }

    def execute_prune(self, action: str, days_threshold: int = 7, skip_codes=()) -> Dict[str, Any]:
        """Safely execute an authorized space reclamation action (never the staging folder of a study being processed)."""
        skip_codes = set(skip_codes or ())
        now = time.time()
        cutoff = now - (days_threshold * 86400)
        reclaimed_bytes = 0
        items_removed = 0

        if action == "prune_scratch":
            if os.path.isdir(self.scratch_dir):
                for root, _, files in os.walk(self.scratch_dir):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            if os.path.getmtime(fp) < cutoff:
                                sz = os.path.getsize(fp)
                                os.remove(fp)
                                reclaimed_bytes += sz
                                items_removed += 1
                        except Exception:
                            pass

        elif action == "prune_staging":
            if os.path.isdir(self.staging_dir):
                for entry in os.listdir(self.staging_dir):
                    ep = os.path.join(self.staging_dir, entry)
                    if os.path.isdir(ep) and os.path.getmtime(ep) < cutoff and entry not in skip_codes:
                        try:
                            sz = sum(os.lstat(os.path.join(r, f)).st_size for r, _, fs in os.walk(ep) for f in fs)
                            shutil.rmtree(ep, ignore_errors=True)
                            reclaimed_bytes += sz
                            items_removed += 1
                        except Exception:
                            pass

        elif action == "prune_failed_runs":
            if os.path.isdir(self.review_dir):
                for f in glob.glob(os.path.join(self.review_dir, "*.incomplete")):
                    try:
                        if os.path.getmtime(f) < cutoff:
                            sz = os.path.getsize(f)
                            os.remove(f)
                            reclaimed_bytes += sz
                            items_removed += 1
                    except Exception:
                        pass

        elif action == "prune_logs":
            if os.path.isdir(self.logs_dir):
                for f in glob.glob(os.path.join(self.logs_dir, "*.log")):
                    try:
                        if os.path.getmtime(f) < cutoff:
                            sz = os.path.getsize(f)
                            os.remove(f)
                            reclaimed_bytes += sz
                            items_removed += 1
                    except Exception:
                        pass

        return {
            "action": action,
            "days_threshold": days_threshold,
            "items_removed": items_removed,
            "reclaimed_bytes": reclaimed_bytes,
            "reclaimed_mb": round(reclaimed_bytes / (1024**2), 2),
        }
