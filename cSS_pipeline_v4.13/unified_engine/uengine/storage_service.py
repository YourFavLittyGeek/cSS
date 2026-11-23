"""uengine/storage_service.py - Comprehensive Storage Intelligence & Live Capacity Service for PERCIVAL.

Provides authoritative OS-level volume capacity measurements for both Mac internal NVMe SSD
and External Data Vault (HDD/SSD), with intelligent category accounting, caching, and health status tiers.
Never performs blocking recursive scans on GUI renders.
"""

import os
import sys
import time
import shutil
import hashlib
import subprocess
from typing import Dict, Any, Optional

TIER_HEALTHY = "HEALTHY"       # > 25% free
TIER_WARNING = "WARNING"       # 20 - 25% free
TIER_CRITICAL = "CRITICAL"     # 10 - 20% free
TIER_EMERGENCY = "EMERGENCY"   # < 10% free
TIER_DISCONNECTED = "DISCONNECTED"

_CACHE: Dict[str, Any] = {}
_LAST_MEASURE_TIME: float = 0.0
_CACHE_TTL: float = 10.0  # seconds to cache folder sizes


def get_volume_mount_point(path: str) -> str:
    """Return the filesystem mount point for path."""
    p = os.path.abspath(path)
    while not os.path.ismount(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def get_volume_name(mount_point: str) -> str:
    """Return friendly volume name from mount point."""
    if mount_point == "/":
        return "Macintosh HD"
    return os.path.basename(mount_point)


def get_volume_uuid(path: str) -> str:
    """Obtain stable hardware UUID for a mounted volume."""
    try:
        out = subprocess.check_output(["diskutil", "info", path], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            if "Volume UUID:" in line:
                return line.split(":", 1)[1].strip()
            if "Disk / Partition UUID:" in line:
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    marker = os.path.join(path, ".percival_vault_uuid")
    if os.path.exists(marker):
        try:
            with open(marker, "r") as f:
                u = f.read().strip()
                if u:
                    return u
        except Exception:
            pass
    return hashlib.sha256(path.encode()).hexdigest()[:16]


def get_dir_size_fast(path: str, max_depth: int = 3) -> int:
    """Fast bounded directory size estimation using os.scandir."""
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    try:
        def _scan(dir_path: str, depth: int):
            nonlocal total
            if depth > max_depth:
                return
            try:
                with os.scandir(dir_path) as it:
                    for entry in it:
                        try:
                            if entry.is_file(follow_symlinks=False):
                                total += entry.stat().st_size
                            elif entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
                                _scan(entry.path, depth + 1)
                        except OSError:
                            continue
            except (PermissionError, OSError):
                pass
        _scan(path, 1)
    except Exception:
        pass
    return total


class StorageService:
    @staticmethod
    def get_overview(base_dir: str, vault_root: Optional[str] = None, force_refresh: bool = False) -> Dict[str, Any]:
        """Aggregate authoritative storage metrics for Mac SSD and External HDD."""
        global _CACHE, _LAST_MEASURE_TIME
        now = time.time()
        if not force_refresh and _CACHE and (now - _LAST_MEASURE_TIME < _CACHE_TTL):
            return _CACHE

        base_dir = os.path.abspath(base_dir)
        mac_mount = get_volume_mount_point(base_dir)
        mac_name = get_volume_name(mac_mount)

        # 1. Authoritative Mac OS volume disk usage
        try:
            mac_usage = shutil.disk_usage(base_dir)
            mac_total_gb = mac_usage.total / (1024**3)
            mac_free_gb = mac_usage.free / (1024**3)
            mac_used_gb = mac_usage.used / (1024**3)
            mac_free_pct = (mac_usage.free / mac_usage.total * 100.0) if mac_usage.total > 0 else 0.0
            mac_used_pct = 100.0 - mac_free_pct
        except Exception as e:
            mac_total_gb = mac_free_gb = mac_used_gb = mac_free_pct = mac_used_pct = 0.0

        if mac_free_pct >= 25.0:
            mac_tier = TIER_HEALTHY
            mac_msg = "Mac internal storage is healthy (>25% free)."
        elif mac_free_pct >= 20.0:
            mac_tier = TIER_WARNING
            mac_msg = "Mac storage warning: 20-25% free space remaining."
        elif mac_free_pct >= 10.0:
            mac_tier = TIER_CRITICAL
            mac_msg = "Mac storage critical: 10-20% free space remaining. Reclaim space before running large jobs."
        else:
            mac_tier = TIER_EMERGENCY
            mac_msg = "EMERGENCY: Less than 10% Mac free storage. Job staging paused."

        # Quick directory sizes for PERCIVAL subfolders
        scratch_p = os.path.join(base_dir, "app_data", "scratch")
        staging_p = os.path.join(base_dir, "app_data", "staging")
        review_p = os.path.join(base_dir, "review")
        data_p = os.path.join(base_dir, "data")
        subjects_p = os.path.join(base_dir, "subjects")
        quarantine_p = os.path.join(base_dir, "app_data", "quarantine")

        scratch_mb = round(get_dir_size_fast(scratch_p) / (1024**2), 1)
        staging_mb = round(get_dir_size_fast(staging_p) / (1024**2), 1)
        review_mb = round(get_dir_size_fast(review_p) / (1024**2), 1)
        data_mb = round(get_dir_size_fast(data_p) / (1024**2), 1)
        subjects_mb = round(get_dir_size_fast(subjects_p) / (1024**2), 1)
        quarantine_mb = round(get_dir_size_fast(quarantine_p) / (1024**2), 1)

        percival_total_mb = scratch_mb + staging_mb + review_mb + data_mb + subjects_mb + quarantine_mb
        percival_managed_gb = round(percival_total_mb / 1024, 2)
        recoverable_est_mb = scratch_mb + staging_mb + quarantine_mb

        mac_info = {
            "volume_name": mac_name,
            "mount_point": mac_mount,
            "path": base_dir,
            "total_gb": round(mac_total_gb, 1),
            "used_gb": round(mac_used_gb, 1),
            "available_gb": round(mac_free_gb, 1),
            "free_pct": round(mac_free_pct, 1),
            "used_pct": round(mac_used_pct, 1),
            "tier": mac_tier,
            "status_message": mac_msg,
            "percival_managed_gb": percival_managed_gb,
            "breakdown": {
                "active_workspace_mb": review_mb + subjects_mb,
                "scratch_mb": scratch_mb,
                "staging_mb": staging_mb,
                "original_mri_mb": data_mb,
                "quarantine_mb": quarantine_mb,
                "estimated_recoverable_mb": recoverable_est_mb,
            }
        }

        # 2. Authoritative External Data Vault volume disk usage
        vault_connected = False
        vault_mount = ""
        vault_uuid = ""
        v_total_gb = v_free_gb = v_used_gb = v_free_pct = v_used_pct = 0.0
        v_vault_bytes = 0
        v_tier = TIER_DISCONNECTED
        v_msg = "No external Data Vault connected."
        v_drive_name = "External Drive"

        v_path = vault_root or ""
        # Auto-detect if not set
        if not v_path or not os.path.exists(v_path):
            vol_dir = "/Volumes"
            if os.path.isdir(vol_dir):
                for ent in os.listdir(vol_dir):
                    cand = os.path.join(vol_dir, ent, "PERCIVAL_VAULT")
                    if os.path.exists(os.path.join(cand, "manifest", "vault_manifest.json")):
                        v_path = cand
                        break

        if v_path and os.path.exists(v_path):
            manifest_p = os.path.join(v_path, "manifest", "vault_manifest.json")
            if os.path.exists(manifest_p):
                vault_connected = True
                vault_mount = get_volume_mount_point(v_path)
                v_drive_name = get_volume_name(vault_mount)
                vault_uuid = get_volume_uuid(vault_mount)
                try:
                    v_usage = shutil.disk_usage(v_path)
                    v_total_gb = v_usage.total / (1024**3)
                    v_free_gb = v_usage.free / (1024**3)
                    v_used_gb = v_usage.used / (1024**3)
                    v_free_pct = (v_usage.free / v_usage.total * 100.0) if v_usage.total > 0 else 0.0
                    v_used_pct = 100.0 - v_free_pct
                except Exception:
                    pass

                if v_free_pct >= 25.0:
                    v_tier = TIER_HEALTHY
                    v_msg = f"External Vault '{v_drive_name}' is connected and healthy."
                elif v_free_pct >= 20.0:
                    v_tier = TIER_WARNING
                    v_msg = f"External Vault '{v_drive_name}' capacity warning (20-25% free)."
                elif v_free_pct >= 10.0:
                    v_tier = TIER_CRITICAL
                    v_msg = f"External Vault '{v_drive_name}' capacity critical (10-20% free)."
                else:
                    v_tier = TIER_EMERGENCY
                    v_msg = f"EMERGENCY: External Vault '{v_drive_name}' is almost full (<10% free)."

                v_vault_bytes = get_dir_size_fast(v_path, max_depth=3)

        # Pending transfer count
        pending_transfers = 0
        queue_p = os.path.join(base_dir, "app_data", "transfer_queue.json")
        if os.path.exists(queue_p):
            try:
                import json
                with open(queue_p, "r") as f:
                    q_data = json.load(f)
                    pending_transfers = sum(1 for it in q_data if it.get("status") in ("pending", "transferring", "PAUSED_DISCONNECTED"))
            except Exception:
                pass

        vault_info = {
            "configured": bool(vault_root),
            "connected": vault_connected,
            "root_path": v_path,
            "volume_name": v_drive_name,
            "mount_point": vault_mount,
            "volume_uuid": vault_uuid,
            "total_gb": round(v_total_gb, 1),
            "used_gb": round(v_used_gb, 1),
            "available_gb": round(v_free_gb, 1),
            "free_pct": round(v_free_pct, 1),
            "used_pct": round(v_used_pct, 1),
            "vault_usage_gb": round(v_vault_bytes / (1024**3), 2),
            "tier": v_tier,
            "status_message": v_msg,
            "pending_transfers": pending_transfers,
            "archive_status": "Synchronized" if vault_connected and pending_transfers == 0 else ("Transfers Pending" if pending_transfers > 0 else "Offline"),
        }

        res = {
            "ok": True,
            "mac_internal": mac_info,
            "external_vault": vault_info,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "updated_timestamp": now,
        }
        _CACHE = res
        _LAST_MEASURE_TIME = now
        return res
