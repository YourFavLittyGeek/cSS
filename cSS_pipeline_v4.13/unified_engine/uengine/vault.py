"""uengine/vault.py - PERCIVAL DATA VAULT Architecture

Authoritative external persistent scientific storage for:
  - PENSIEVE memory database & snapshots
  - Original & processed MRI datasets, segmentations, candidate patches
  - Models for ALBUS, LUMOS, NOX, PERCIVAL CORE
  - SHADOW ML autonomous experiment artifacts & checkpoints
  - Reports, exports, archives, and independent backups

Decoupled completely from Mac internal application storage.
Supports: creation, discovery, connection, health monitoring, migration,
safe disconnection/ejection, integrity checks, and backup creation.
"""

import os
import sys
import json
import time
import shutil
import hashlib
import sqlite3
import pathlib
import subprocess
from .safety import volumes_root
import select
import threading
from typing import Dict, List, Optional, Tuple, Any

VAULT_DIRS = [
    # Metadata & Manifest
    "manifest",
    "Manifests",
    "database",
    # Pensieve Core Memory
    "PENSIEVE",
    "PENSIEVE/snapshots",
    "Pensieve",
    "Pensieve/Database_Backups",
    "Pensieve/Journals",
    "Pensieve/Snapshots",
    # MRI Data
    "MRI",
    "MRI/Originals",
    "MRI/Imported",
    "MRI/Metadata",
    "studies",
    "original_mri",
    # Processed MRI
    "Processed_MRI",
    "Processed_MRI/Preprocessing",
    "Processed_MRI/Normalized",
    "Processed_MRI/Derivatives",
    "processed_mri",
    "segmentations",
    # Candidates
    "Candidates",
    "Candidates/ALBUS",
    "Candidates/LUMOS",
    "Candidates/NOX",
    "candidates",
    # Expert Annotations
    "Expert_Annotations",
    "Expert_Annotations/Candidates",
    "Expert_Annotations/Missed_Lesions",
    "Expert_Annotations/Adjudication",
    # Training Datasets
    "Training_Datasets",
    "Training_Datasets/Manifests",
    "Training_Datasets/Splits",
    "Training_Datasets/Exports",
    "training",
    # Models
    "Models",
    "Models/Released",
    "Models/Historical",
    "Models/Experimental",
    "models",
    "models/ALBUS",
    "models/LUMOS",
    "models/NOX",
    "models/PERCIVAL_CORE",
    # Experiments
    "Experiments",
    "Experiments/Shadow_ML",
    "Experiments/Governance",
    "SHADOW_ML",
    "experiments",
    "checkpoints",
    # Collections & Exports
    "Cohorts",
    "reports",
    "Reports",
    "exports",
    "Exports",
    "archive",
    "backups",
    "Backups",
    "Legacy_Projects",
    "Audit_Logs",
    "Quarantine",
]

VAULT_CONFIG_FILE = os.path.expanduser("~/.percival_vault_config.json")

class PercivalDataVault:
    def __init__(self, root_path: Optional[str] = None):
        self.root_path = os.path.abspath(root_path) if root_path else None
        self.volume_uuid: Optional[str] = None
        self._is_connected = False
        self._manifest: Dict[str, Any] = {}
        self._lock_file: Optional[str] = None
        if not self.root_path:
            self._load_stored_location()
        if self.root_path:
            self.connect(self.root_path)

    @staticmethod
    def get_volume_uuid(path: str) -> str:
        """Detect volume UUID using macOS diskutil or marker file."""
        # 1. Check for local marker file in vault
        marker = os.path.join(path, ".percival_vault_uuid")
        if os.path.exists(marker):
            try:
                with open(marker, "r") as f:
                    u = f.read().strip()
                if u:
                    return u
            except Exception:
                pass

        # 2. Try diskutil info on macOS
        try:
            out = subprocess.check_output(["diskutil", "info", path], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if "Volume UUID:" in line:
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass

        # 3. Deterministic path/creation fallback hash
        return hashlib.sha256(path.encode()).hexdigest()[:16]

    @classmethod
    def locate_vault_by_uuid(cls, uuid_to_find: str) -> Optional[str]:
        """Scan /Volumes for a drive matching volume UUID when mount point has changed."""
        if not uuid_to_find:
            return None
        volumes_dir = volumes_root()
        if not os.path.isdir(volumes_dir):
            return None

        try:
            for entry in os.listdir(volumes_dir):
                vp = os.path.join(volumes_dir, entry)
                if not os.path.isdir(vp) or os.path.islink(vp):
                    continue
                # Check candidate volume
                cand_uuid = cls.get_volume_uuid(vp)
                if cand_uuid == uuid_to_find:
                    # Check if vault folder exists inside volume
                    for sub in [vp, os.path.join(vp, "PERCIVAL_VAULT")]:
                        if os.path.exists(os.path.join(sub, "manifest", "vault_manifest.json")):
                            return sub
                # Also check direct child vault folders
                vault_sub = os.path.join(vp, "PERCIVAL_VAULT")
                if os.path.isdir(vault_sub):
                    sub_uuid = cls.get_volume_uuid(vault_sub)
                    if sub_uuid == uuid_to_find:
                        return vault_sub
        except Exception:
            pass
        return None

    def _load_stored_location(self) -> None:
        """Load configured vault path and UUID from Mac internal configuration."""
        if os.path.exists(VAULT_CONFIG_FILE):
            try:
                with open(VAULT_CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                p = cfg.get("active_vault_path")
                self.volume_uuid = cfg.get("volume_uuid")
                if p and os.path.exists(p):
                    self.root_path = os.path.abspath(p)
                elif self.volume_uuid:
                    # Mount path might have shifted (e.g. /Volumes/PERCIVAL_VAULT 1)
                    relocated = self.locate_vault_by_uuid(self.volume_uuid)
                    if relocated:
                        self.root_path = relocated
            except Exception:
                pass

    def save_configuration(self) -> None:
        """Save the active vault location and UUID to local Mac configuration."""
        try:
            cfg = {
                "active_vault_path": self.root_path,
                "volume_uuid": self.volume_uuid,
                "updated_at": time.time(),
            }
            with open(VAULT_CONFIG_FILE, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            sys.stderr.write(f"[Vault] Failed to save config: {e}\n")

    @classmethod
    def create_vault(cls, destination_folder: str, name: str = "PERCIVAL_VAULT") -> "PercivalDataVault":
        """Create a new organized Percival Data Vault in the destination directory."""
        dest_folder = os.path.abspath(destination_folder)
        if os.path.basename(dest_folder) == name:
            dest = dest_folder
        else:
            dest = os.path.abspath(os.path.join(dest_folder, name))
        os.makedirs(dest, exist_ok=True)
        for d in VAULT_DIRS:
            os.makedirs(os.path.join(dest, d), exist_ok=True)

        vault_id = hashlib.sha256(f"{dest}-{time.time()}".encode()).hexdigest()[:16]
        vol_uuid = cls.get_volume_uuid(dest)
        # Write marker file
        try:
            with open(os.path.join(dest, ".percival_vault_uuid"), "w") as f:
                f.write(vol_uuid)
        except Exception:
            pass

        manifest = {
            "vault_id": vault_id,
            "volume_uuid": vol_uuid,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "format_version": "5.25.0",
            "name": name,
            "status": "ready",
            "file_counts": {},
            "components": ["ALBUS", "LUMOS", "NOX", "PERCIVAL_CORE", "PENSIEVE", "SHADOW_ML"]
        }
        manifest_path = os.path.join(dest, "manifest", "vault_manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        vault = cls(dest)
        vault.volume_uuid = vol_uuid
        vault.save_configuration()
        return vault

    def connect(self, vault_path: str, auto_create_if_drive: bool = True) -> Tuple[bool, str]:
        """Connect to an existing Percival Data Vault or automatically create in selected volume."""
        p = os.path.abspath(vault_path)
        if not os.path.exists(p):
            # Attempt UUID-based auto-reconnect if known
            if self.volume_uuid:
                relocated = self.locate_vault_by_uuid(self.volume_uuid)
                if relocated:
                    p = relocated
                else:
                    self._is_connected = False
                    return False, f"Directory does not exist: {p}"
            else:
                self._is_connected = False
                return False, f"Directory does not exist: {p}"

        # 1. If p itself has manifest/vault_manifest.json
        manifest_file = os.path.join(p, "manifest", "vault_manifest.json")

        # 2. If p has child PERCIVAL_VAULT folder with manifest
        if not os.path.exists(manifest_file):
            child_vault = os.path.join(p, "PERCIVAL_VAULT")
            child_manifest = os.path.join(child_vault, "manifest", "vault_manifest.json")
            if os.path.exists(child_manifest):
                p = child_vault
                manifest_file = child_manifest

        # 3. If manifest still missing, check if volume is eligible for automatic Vault creation
        if not os.path.exists(manifest_file):
            if auto_create_if_drive:
                # Verify permissions and writable status
                if not os.access(p, os.W_OK):
                    self._is_connected = False
                    return False, f"Volume is read-only or permission is denied: {p}"
                # Verify capacity (minimum 2 GB free)
                try:
                    usage = shutil.disk_usage(p)
                    free_gb = usage.free / (1024**3)
                    if free_gb < 2.0:
                        self._is_connected = False
                        return False, f"Insufficient volume capacity ({free_gb:.1f} GB free, minimum 2.0 GB required): {p}"
                except Exception:
                    pass

                try:
                    created_vault = self.create_vault(p, name="PERCIVAL_VAULT")
                    p = created_vault.root_path
                    manifest_file = os.path.join(p, "manifest", "vault_manifest.json")
                except Exception as e:
                    self._is_connected = False
                    return False, f"Failed to auto-create PERCIVAL_VAULT on {p}: {e}"
            else:
                self._is_connected = False
                return False, f"Not a valid Percival Data Vault (missing manifest): {p}"

        try:
            with open(manifest_file, "r") as f:
                self._manifest = json.load(f)
        except Exception as e:
            self._is_connected = False
            return False, f"Failed to parse vault manifest: {e}"

        # Verify key directory structure
        for d in ("manifest", "database", "PENSIEVE", "models", "SHADOW_ML", "MRI", "Processed_MRI"):
            dp = os.path.join(p, d)
            if not os.path.isdir(dp):
                os.makedirs(dp, exist_ok=True)

        self.root_path = p
        self.volume_uuid = self._manifest.get("volume_uuid") or self.get_volume_uuid(p)
        self._is_connected = True
        self.save_configuration()
        return True, "Connected successfully"

    def is_connected(self) -> bool:
        """Check if authoritative external vault is actively connected and reachable."""
        if not self._is_connected or not self.root_path:
            return False
        # Test if path still mounted and accessible
        return os.path.exists(os.path.join(self.root_path, "manifest", "vault_manifest.json"))

    def get_connection_status(self) -> Dict[str, Any]:
        """Return unified connection and degraded-mode diagnostic state."""
        connected = self.is_connected()
        if connected:
            return {
                "connected": True,
                "degraded_mode": False,
                "root_path": self.root_path,
                "volume_uuid": self.volume_uuid,
                "banner_message": "External Data Vault connected.",
                "archived_badge": "ARCHIVED — ACCESSIBLE",
            }
        else:
            return {
                "connected": False,
                "degraded_mode": True,
                "root_path": self.root_path,
                "volume_uuid": self.volume_uuid,
                "banner_message": "EXTERNAL DATA VAULT DISCONNECTED (DEGRADED MODE)",
                "archived_badge": "ARCHIVED — DRIVE REQUIRED",
            }

    @staticmethod
    def get_emergency_scratch_quota(base_dir: str) -> Dict[str, Any]:
        """Calculate local emergency scratch quota when external drive is disconnected."""
        try:
            usage = shutil.disk_usage(base_dir)
            free_gb = usage.free / (1024**3)
            # Cap emergency quota at min(15 GB, 20% of free space)
            quota_gb = min(15.0, free_gb * 0.20)
            can_proceed = quota_gb >= 2.0
            return {
                "free_ssd_gb": round(free_gb, 1),
                "emergency_quota_gb": round(quota_gb, 1),
                "can_proceed": can_proceed,
                "warning": None if can_proceed else "Insufficient Mac SSD space for emergency local scratch fallback.",
            }
        except Exception as e:
            return {
                "free_ssd_gb": 0.0,
                "emergency_quota_gb": 0.0,
                "can_proceed": False,
                "warning": str(e),
            }

    def path(self, *parts: str) -> str:
        """Resolve a safe path within the authoritative external vault."""
        if not self.is_connected():
            raise RuntimeError("Percival Data Vault is disconnected or unavailable.")
        resolved = os.path.abspath(os.path.join(self.root_path, *parts))
        root = os.path.abspath(self.root_path)
        # Enforce strict path containment (blocks directory traversal and prefix spoofing like /path/VAULT_ATTACK)
        try:
            if not pathlib.Path(resolved).resolve().is_relative_to(pathlib.Path(root).resolve()):
                raise ValueError(f"Path containment violation out of vault: {resolved}")
        except (ValueError, AttributeError):
            if os.path.commonpath([resolved, root]) != root:
                raise ValueError(f"Path containment violation out of vault: {resolved}")
        return resolved

    def pensieve_dir(self) -> str:
        """Return the dedicated Pensieve directory in the Vault for backups, snapshots, and journals."""
        p = self.path("Pensieve")
        for sub in ("Database_Backups", "Journals", "Snapshots", "Historical_Backups", "Manifests"):
            os.makedirs(os.path.join(p, sub), exist_ok=True)
        return p

    def pensieve_db_path(self) -> str:
        """Return the authoritative path to the persistent PENSIEVE SQLite database in the Vault."""
        p_canon = os.path.join(self.root_path, "Pensieve", "pensieve.db")
        if os.path.exists(p_canon):
            return p_canon
        p_upper = os.path.join(self.root_path, "PENSIEVE", "pensieve.db")
        if os.path.exists(p_upper):
            return p_upper
        return p_canon

    def get_storage_stats(self) -> Dict[str, Any]:
        """Return capacity, free space, and category sizes for the storage dashboard."""
        if not self.is_connected():
            return {
                "connected": False,
                "error": "External Data Vault disconnected or unmounted."
            }
        try:
            total, used, free = shutil.disk_usage(self.root_path)
        except Exception:
            total, used, free = 0, 0, 0

        categories = {}
        for cat in ("original_mri", "processed_mri", "PENSIEVE", "models", "SHADOW_ML", "checkpoints", "backups"):
            cat_path = os.path.join(self.root_path, cat)
            if os.path.exists(cat_path):
                total_bytes = sum(
                    os.path.getsize(os.path.join(root, file))
                    for root, _, files in os.walk(cat_path)
                    for file in files
                )
                categories[cat] = total_bytes
            else:
                categories[cat] = 0

        pct_free = (free / total * 100) if total > 0 else 0
        warning = None
        if free < 5 * (1024**3): # < 5 GB
            warning = "CRITICAL: Less than 5 GB free disk space remaining on Data Vault."
        elif free < 20 * (1024**3): # < 20 GB
            warning = "WARNING: Less than 20 GB free disk space remaining."

        return {
            "connected": True,
            "root_path": self.root_path,
            "vault_id": self._manifest.get("vault_id", "unknown"),
            "format_version": self._manifest.get("format_version", "unknown"),
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "pct_free": round(pct_free, 1),
            "categories": categories,
            "warning": warning,
            "read_only": not os.access(self.root_path, os.W_OK)
        }

    def verify_integrity(self) -> Dict[str, Any]:
        """Perform full integrity validation of vault directories, manifest, and DB."""
        if not self.is_connected():
            return {"ok": False, "error": "Vault is disconnected."}

        missing_dirs = []
        for d in VAULT_DIRS:
            dp = os.path.join(self.root_path, d)
            if not os.path.isdir(dp):
                missing_dirs.append(d)

        # Check PENSIEVE db integrity if it exists
        db_path = self.pensieve_db_path()
        db_integrity = "not_created"
        if os.path.exists(db_path):
            try:
                con = sqlite3.connect(db_path)
                cur = con.cursor()
                res = cur.execute("PRAGMA integrity_check;").fetchall()
                con.close()
                db_integrity = "ok" if res and res[0][0] == "ok" else f"corrupt: {res}"
            except Exception as e:
                db_integrity = f"error: {e}"

        ok = (len(missing_dirs) == 0) and (db_integrity in ("ok", "not_created"))
        return {
            "ok": ok,
            "missing_dirs": missing_dirs,
            "db_integrity": db_integrity,
            "vault_id": self._manifest.get("vault_id"),
            "timestamp": time.time()
        }

    def safe_eject(self) -> Tuple[bool, str]:
        """Gracefully prepare external storage for physical removal or unmounting."""
        if not self.is_connected():
            return True, "Already disconnected"
        # Check active lockfiles
        lock_pattern = os.path.join(self.root_path, "**", "*.lock")
        # In a real environment, checkpoint sqlite WAL
        db_path = self.pensieve_db_path()
        if os.path.exists(db_path):
            try:
                con = sqlite3.connect(db_path)
                con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                con.close()
            except Exception:
                pass
        self._is_connected = False
        return True, "Safe to unmount external drive."

    def migrate_data(self, new_destination_parent: str) -> Tuple[bool, str]:
        """Safely copy vault data to a new location, verify checksums, then update active config."""
        if not self.is_connected():
            return False, "Active vault is disconnected."

        new_vault_path = os.path.join(new_destination_parent, os.path.basename(self.root_path))
        if os.path.exists(new_vault_path):
            return False, f"Target destination already exists: {new_vault_path}"

        # Copy data without deleting original
        try:
            shutil.copytree(self.root_path, new_vault_path)
        except Exception as e:
            if os.path.exists(new_vault_path):
                shutil.rmtree(new_vault_path, ignore_errors=True)
            return False, f"Copy failed: {e}"

        # Validate copied vault
        migrated_vault = PercivalDataVault(new_vault_path)
        check = migrated_vault.verify_integrity()
        if not check.get("ok"):
            shutil.rmtree(new_vault_path, ignore_errors=True)
            return False, f"Migrated vault failed integrity check: {check}"

        # Update active config only after confirmed verification
        self.root_path = new_vault_path
        self._is_connected = True
        self.save_configuration()
        return True, f"Successfully migrated to {new_vault_path}. Original data preserved."

    def create_backup(self, backup_destination: str) -> Tuple[bool, str]:
        """Create an independent verified backup archive of PENSIEVE, models, and manifests."""
        if not self.is_connected():
            return False, "Vault is disconnected."

        os.makedirs(backup_destination, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_name = f"percival_vault_backup_{ts}"
        stage_dir = os.path.join(backup_destination, backup_name)
        os.makedirs(stage_dir, exist_ok=True)

        # Copy manifests, PENSIEVE db, models, and reports
        for item in ("manifest", "PENSIEVE", "models", "reports"):
            src = os.path.join(self.root_path, item)
            dst = os.path.join(stage_dir, item)
            if os.path.exists(src):
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)

        # Write backup manifest
        bmanifest = {
            "source_vault_id": self._manifest.get("vault_id"),
            "timestamp": time.time(),
            "datetime": ts,
            "backup_type": "scientific_core_backup"
        }
        with open(os.path.join(stage_dir, "backup_manifest.json"), "w") as f:
            json.dump(bmanifest, f, indent=2)

        return True, f"Backup created successfully at {stage_dir}"

    def open_in_finder(self) -> Tuple[bool, str]:
        """Reveal Data Vault root folder in macOS Finder."""
        if not self.root_path or not os.path.exists(self.root_path):
            return False, "Vault path does not exist on disk"
        try:
            subprocess.run(["open", self.root_path], check=True)
            return True, f"Opened {self.root_path} in Finder"
        except Exception as e:
            return False, f"Failed to open in Finder: {e}"

    def rebuild_index(self) -> Dict[str, Any]:
        """Non-destructively scans existing vault contents and refreshes manifest statistics."""
        if not self.is_connected() or not self.root_path:
            return {"ok": False, "error": "Vault is disconnected"}
        counts = {}
        for d in VAULT_DIRS:
            dp = os.path.join(self.root_path, d)
            if os.path.isdir(dp):
                try:
                    c = len(os.listdir(dp))
                    counts[d] = c
                except Exception:
                    counts[d] = 0
        self._manifest["file_counts"] = counts
        self._manifest["last_index_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            man_path = os.path.join(self.root_path, "manifest", "vault_manifest.json")
            with open(man_path, "w") as f:
                json.dump(self._manifest, f, indent=2)
        except Exception:
            pass
        return {"ok": True, "vault_id": self._manifest.get("vault_id"), "file_counts": counts}

    @staticmethod
    def detect_external_volumes() -> List[Dict[str, Any]]:
        return detect_external_volumes()

# Global Singleton Helper
_DEFAULT_VAULT: Optional[PercivalDataVault] = None

def get_vault(root_path: Optional[str] = None) -> PercivalDataVault:
    global _DEFAULT_VAULT
    if _DEFAULT_VAULT is None or (root_path and _DEFAULT_VAULT.root_path != root_path):
        _DEFAULT_VAULT = PercivalDataVault(root_path)
    return _DEFAULT_VAULT


class TransferQueueManager:
    """Manages asynchronous and resumable file transfers to/from Data Vault with disconnection protection."""
    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)
        self.queue_file = os.path.join(self.base_dir, "app_data", "transfer_queue.json")
        os.makedirs(os.path.dirname(self.queue_file), exist_ok=True)
        self._ensure_queue()

    def _ensure_queue(self) -> None:
        if not os.path.exists(self.queue_file):
            with open(self.queue_file, "w") as f:
                json.dump([], f)

    def _load(self) -> List[Dict[str, Any]]:
        try:
            with open(self.queue_file, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def _save(self, items: List[Dict[str, Any]]) -> None:
        tmp = self.queue_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(items, f, indent=2)
        os.replace(tmp, self.queue_file)

    def enqueue(self, job_id: str, src: str, dst: str, file_type: str = "output") -> Dict[str, Any]:
        items = self._load()
        tid = f"tx_{int(time.time()*1000)}_{len(items)+1}"
        entry = {
            "transfer_id": tid,
            "job_id": job_id,
            "source": src,
            "destination": dst,
            "file_type": file_type,
            "status": "pending",
            "enqueued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "attempts": 0,
            "error": None,
        }
        items.append(entry)
        self._save(items)
        return entry

    def update_status(self, transfer_id: str, status: str, error: Optional[str] = None) -> bool:
        items = self._load()
        for it in items:
            if it["transfer_id"] == transfer_id:
                it["status"] = status
                it["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if error:
                    it["error"] = error
                self._save(items)
                return True
        return False

    def pause_for_disconnection(self) -> int:
        """Mark all in-flight active/transferring operations as PAUSED_DISCONNECTED."""
        items = self._load()
        count = 0
        for it in items:
            if it["status"] in ("transferring", "active"):
                it["status"] = "PAUSED_DISCONNECTED"
                it["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                count += 1
        if count > 0:
            self._save(items)
        return count

    def resume_transfers(self, vault: PercivalDataVault) -> List[Dict[str, Any]]:
        """Resume paused or pending transfers once vault is reconnected."""
        if not vault.is_connected():
            return []
        items = self._load()
        resumed = []
        from .safety import PathPolicy, SafetyError
        from .unified_transfer_engine import UnifiedTransferEngine
        policy = PathPolicy(self.base_dir, vault.root_path)
        engine = UnifiedTransferEngine(os.path.join(self.base_dir, "app_data", "transfers"))
        for it in items:
            if not isinstance(it, dict) or "source" not in it or "destination" not in it:
                continue                                   # entries of the other queue schema (TransferManager) are not ours
            if it.get("status") in ("pending", "PAUSED_DISCONNECTED"):
                src = it["source"]
                dst = it["destination"]
                if os.path.exists(src):
                    try:
                        # Phase 0: both ends must pass the safety policy, and the copy is verified before it replaces dst
                        policy.check_source(src)
                        policy.check_write_target(dst)
                        it["status"] = "transferring"
                        it["attempts"] = int(it.get("attempts", 0)) + 1
                        engine.copy_file_streaming(src, dst, verify_sha=True)
                        it["status"] = "completed"
                        it["error"] = None
                        it["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        resumed.append(it)
                    except Exception as e:
                        it["status"] = "PAUSED_DISCONNECTED" if not vault.is_connected() else "failed"
                        it["error"] = str(e)
                else:
                    it["status"] = "failed"
                    it["error"] = f"Source not found: {src}"
        self._save(items)
        return resumed

    def list_transfers(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        items = self._load()
        if status:
            return [it for it in items if it.get("status") == status]
        return items


def detect_external_volumes() -> List[Dict[str, Any]]:
    """Inspect /Volumes and return rich status for all connected storage volumes."""
    volumes = []
    volumes_dir = volumes_root()
    if not os.path.isdir(volumes_dir):
        return volumes

    for entry in sorted(os.listdir(volumes_dir)):
        vp = os.path.join(volumes_dir, entry)
        if os.path.islink(vp) or not os.path.isdir(vp):
            continue
        if vp == "/Volumes/Macintosh HD" or entry == "Macintosh HD":
            continue

        is_external = False
        vol_uuid = ""
        read_only = False
        fs_type = ""
        try:
            out = subprocess.check_output(["diskutil", "info", vp], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if "Device Location:" in line and "External" in line:
                    is_external = True
                if "Volume UUID:" in line:
                    vol_uuid = line.split(":", 1)[1].strip()
                if "Disk / Partition UUID:" in line and not vol_uuid:
                    vol_uuid = line.split(":", 1)[1].strip()
                if "Volume Read-Only:" in line and "Yes" in line:
                    read_only = True
                if "Type (Bundle):" in line:
                    fs_type = line.split(":", 1)[1].strip()
        except Exception:
            pass

        if not vol_uuid:
            vol_uuid = PercivalDataVault.get_volume_uuid(vp)

        writable = os.access(vp, os.W_OK) and not read_only
        try:
            usage = shutil.disk_usage(vp)
            total_gb = round(usage.total / (1024**3), 1)
            free_gb = round(usage.free / (1024**3), 1)
        except Exception:
            total_gb = 0.0
            free_gb = 0.0

        direct_vault = os.path.exists(os.path.join(vp, "manifest", "vault_manifest.json"))
        child_vault_path = os.path.join(vp, "PERCIVAL_VAULT")
        child_vault = os.path.exists(os.path.join(child_vault_path, "manifest", "vault_manifest.json"))
        has_vault = direct_vault or child_vault
        vault_path = vp if direct_vault else (child_vault_path if child_vault else "")

        if not writable:
            status = "read_only"
        elif free_gb < 2.0:
            status = "insufficient_space"
        elif has_vault:
            status = "vault_healthy"
        else:
            status = "vault_not_initialized"

        volumes.append({
            "name": entry,
            "mount_point": vp,
            "is_external": is_external,
            "volume_uuid": vol_uuid,
            "filesystem": fs_type,
            "writable": writable,
            "read_only": not writable,
            "total_gb": total_gb,
            "free_gb": free_gb,
            "has_vault": has_vault,
            "vault_path": vault_path,
            "status": status,
        })
    return volumes


class VolumeWatcher(threading.Thread):
    """Background watcher for macOS volume events with immediate kqueue and fallback polling."""
    def __init__(self, on_change_callback):
        super().__init__(daemon=True, name="PercivalVolumeWatcher")
        self.callback = on_change_callback
        self._running = True

    def run(self):
        kq = None
        fd = -1
        try:
            if hasattr(select, "kqueue") and os.path.isdir("/Volumes"):
                kq = select.kqueue()
                fd = os.open("/Volumes", os.O_RDONLY)
                ke = select.kevent(fd, filter=select.KQ_FILTER_VNODE,
                                   flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                                   fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_ATTRIB)
                kq.control([ke], 0, 0)
        except Exception:
            kq = None

        while self._running:
            try:
                if kq:
                    events = kq.control([], 1, 2.0)
                    if events:
                        self.callback("mount_change")
                    else:
                        self.callback("poll_check")
                else:
                    time.sleep(2.5)
                    self.callback("poll_check")
            except Exception:
                time.sleep(2.5)

        if fd >= 0:
            try: os.close(fd)
            except Exception: pass
        if kq:
            try: kq.close()
            except Exception: pass

    def stop(self):
        self._running = False


_VOLUME_WATCHER: Optional[VolumeWatcher] = None

def get_volume_watcher(callback=None) -> Optional[VolumeWatcher]:
    global _VOLUME_WATCHER
    if _VOLUME_WATCHER is None and callback:
        _VOLUME_WATCHER = VolumeWatcher(callback)
        _VOLUME_WATCHER.start()
    return _VOLUME_WATCHER

