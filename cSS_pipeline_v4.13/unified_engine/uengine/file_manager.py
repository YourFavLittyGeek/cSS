"""file_manager.py - Integrated File Manager & Storage Dashboard Backend for PERCIVAL.

Manages dual-storage topology between Mac internal SSD and External Data Vault:
- Status classifications: LOCAL_ONLY, STAGED, ARCHIVED, SYNCHRONIZED, ARCHIVED_DRIVE_REQUIRED
- Actions: Browse trees, Stage to SSD, Archive to Data Vault, Verify SHA-256, Clean staging, Delete
"""

import glob
import hashlib
import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from .unified_transfer_engine import get_transfer_engine

STATUS_LOCAL_ONLY = "LOCAL_ONLY"
STATUS_STAGED = "STAGED"
STATUS_ARCHIVED = "ARCHIVED"
STATUS_SYNCHRONIZED = "SYNCHRONIZED"
STATUS_DRIVE_REQUIRED = "ARCHIVED_DRIVE_REQUIRED"


def compute_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


class FileManager:
    def __init__(self, base_dir: str, vault_root: Optional[str] = None):
        self.base_dir = os.path.abspath(base_dir)
        self.vault_root = os.path.abspath(vault_root) if vault_root else None
        self.app_data_dir = os.path.join(self.base_dir, "app_data")
        self.staging_dir = os.path.join(self.app_data_dir, "staging")
        self.review_dir = os.path.join(self.base_dir, "review")
        os.makedirs(self.staging_dir, exist_ok=True)
        os.makedirs(self.review_dir, exist_ok=True)

    def is_vault_connected(self) -> bool:
        if not self.vault_root:
            return False
        return os.path.exists(os.path.join(self.vault_root, "manifest", "vault_manifest.json"))

    def get_storage_overview(self) -> Dict[str, Any]:
        """Aggregate high-level capacity and health metrics across local SSD and external Data Vault."""
        # Local SSD stats
        local_usage = shutil.disk_usage(self.base_dir)
        local_total_gb = local_usage.total / (1024**3)
        local_free_gb = local_usage.free / (1024**3)
        local_used_gb = local_usage.used / (1024**3)
        local_free_pct = (local_usage.free / local_usage.total * 100) if local_usage.total > 0 else 0

        # Data Vault stats
        vault_connected = self.is_vault_connected()
        vault_stats = {
            "configured": bool(self.vault_root),
            "connected": vault_connected,
            "root_path": self.vault_root,
            "total_gb": 0.0,
            "free_gb": 0.0,
            "used_gb": 0.0,
            "free_pct": 0.0,
        }
        if vault_connected and self.vault_root:
            v_usage = shutil.disk_usage(self.vault_root)
            vault_stats.update({
                "total_gb": round(v_usage.total / (1024**3), 1),
                "free_gb": round(v_usage.free / (1024**3), 1),
                "used_gb": round(v_usage.used / (1024**3), 1),
                "free_pct": round((v_usage.free / v_usage.total * 100), 1) if v_usage.total > 0 else 0.0,
            })

        # Study counts
        studies = self.list_studies()
        status_counts = {}
        for s in studies:
            status_counts[s["status"]] = status_counts.get(s["status"], 0) + 1

        return {
            "local_ssd": {
                "path": self.base_dir,
                "total_gb": round(local_total_gb, 1),
                "used_gb": round(local_used_gb, 1),
                "free_gb": round(local_free_gb, 1),
                "free_pct": round(local_free_pct, 1),
                "warning": local_free_gb < 20.0,
            },
            "data_vault": vault_stats,
            "total_studies": len(studies),
            "status_counts": status_counts,
        }

    def list_studies(self, filter_status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all known studies across local workspace and external Data Vault with lifecycle status."""
        studies: Dict[str, Dict[str, Any]] = {}

        # 1. Inspect local review and staging
        if os.path.isdir(self.review_dir):
            for f in os.listdir(self.review_dir):
                if f.endswith("_candidates.csv"):
                    code = f.replace("_candidates.csv", "")
                    studies[code] = {
                        "study_code": code,
                        "local_present": True,
                        "staged_present": False,
                        "vault_present": False,
                        "local_size_mb": round(os.path.getsize(os.path.join(self.review_dir, f)) / (1024**2), 2),
                        "vault_size_mb": 0.0,
                        "status": STATUS_LOCAL_ONLY,
                    }

        if os.path.isdir(self.staging_dir):
            for entry in os.listdir(self.staging_dir):
                sp = os.path.join(self.staging_dir, entry)
                if os.path.isdir(sp):
                    st = studies.setdefault(entry, {
                        "study_code": entry,
                        "local_present": False,
                        "staged_present": True,
                        "vault_present": False,
                        "local_size_mb": 0.0,
                        "vault_size_mb": 0.0,
                        "status": STATUS_STAGED,
                    })
                    st["staged_present"] = True

        # 2. Inspect External Data Vault if configured
        vault_connected = self.is_vault_connected()
        EXCLUDED_VAULT_DIRS = {"derivatives", "normalized", "preprocessing", "manifest", "checkpoints", "quarantine", "database", "backups", "reports"}
        if self.vault_root and os.path.isdir(self.vault_root):
            for sub in ("studies", "archive", "processed_mri"):
                sub_dir = os.path.join(self.vault_root, sub)
                if os.path.isdir(sub_dir):
                    for entry in os.listdir(sub_dir):
                        if entry.startswith(".") or entry.lower() in EXCLUDED_VAULT_DIRS:
                            continue
                        ep = os.path.join(sub_dir, entry)
                        if os.path.isdir(ep):
                            has_files = any(f.endswith((".nii", ".nii.gz", ".csv", ".json")) for f in os.listdir(ep))
                            if not has_files:
                                continue
                        code = entry.replace(".nii.gz", "").replace(".nii", "").replace("_candidates.csv", "")
                        st = studies.setdefault(code, {
                            "study_code": code,
                            "local_present": False,
                            "staged_present": False,
                            "vault_present": True,
                            "local_size_mb": 0.0,
                            "vault_size_mb": 0.0,
                            "status": STATUS_ARCHIVED,
                        })
                        st["vault_present"] = True
        elif self.vault_root and not vault_connected:
            # Vault is configured but disconnected
            for code, st in list(studies.items()):
                if st.get("vault_present") and not st.get("local_present"):
                    st["status"] = STATUS_DRIVE_REQUIRED

        # 3. Determine status for each study
        result = []
        for code, st in sorted(studies.items()):
            lp = st["local_present"]
            vp = st["vault_present"]
            sp = st["staged_present"]

            if not vault_connected and vp and not lp:
                st["status"] = STATUS_DRIVE_REQUIRED
            elif lp and vp:
                st["status"] = STATUS_SYNCHRONIZED
            elif sp and not vp:
                st["status"] = STATUS_STAGED
            elif lp and not vp:
                st["status"] = STATUS_LOCAL_ONLY
            elif vp and not lp:
                st["status"] = STATUS_ARCHIVED

            if not filter_status or st["status"] == filter_status:
                result.append(st)

        return result

    def browse_study_tree(self, study_code: str) -> Dict[str, Any]:
        """Return file hierarchy and detailed metadata for a given study."""
        local_files = []
        # Check review
        if os.path.isdir(self.review_dir):
            for f in glob.glob(os.path.join(self.review_dir, f"{study_code}*")):
                local_files.append({
                    "name": os.path.basename(f),
                    "path": f,
                    "location": "review",
                    "size_bytes": os.path.getsize(f),
                    "modified": os.path.getmtime(f),
                })
        # Check staging
        stg_dir = os.path.join(self.staging_dir, study_code)
        if os.path.isdir(stg_dir):
            for root, _, files in os.walk(stg_dir):
                for f in files:
                    fp = os.path.join(root, f)
                    local_files.append({
                        "name": f,
                        "path": fp,
                        "location": "staging",
                        "size_bytes": os.path.getsize(fp),
                        "modified": os.path.getmtime(fp),
                    })

        # Check vault
        vault_files = []
        vault_connected = self.is_vault_connected()
        if vault_connected and self.vault_root:
            for sub in ("studies", "archive", "processed_mri"):
                cand_dir = os.path.join(self.vault_root, sub, study_code)
                if os.path.isdir(cand_dir):
                    for root, _, files in os.walk(cand_dir):
                        for f in files:
                            fp = os.path.join(root, f)
                            vault_files.append({
                                "name": f,
                                "path": fp,
                                "location": f"vault/{sub}",
                                "size_bytes": os.path.getsize(fp),
                                "modified": os.path.getmtime(fp),
                            })

        return {
            "study_code": study_code,
            "vault_connected": vault_connected,
            "local_files_count": len(local_files),
            "vault_files_count": len(vault_files),
            "local_files": local_files,
            "vault_files": vault_files,
        }

    def stage_study(self, study_code: str) -> Dict[str, Any]:
        """Stage files from external Data Vault to local Mac SSD staging."""
        if not self.is_vault_connected() or not self.vault_root:
            raise RuntimeError("Data Vault is disconnected. Cannot stage.")

        dest_dir = os.path.join(self.staging_dir, study_code)
        os.makedirs(dest_dir, exist_ok=True)

        staged = []
        for sub in ("studies", "archive", "original_mri"):
            src_dir = os.path.join(self.vault_root, sub, study_code)
            if os.path.isdir(src_dir):
                for f in os.listdir(src_dir):
                    sp = os.path.join(src_dir, f)
                    if os.path.isfile(sp):
                        dp = os.path.join(dest_dir, f)
                        shutil.copy2(sp, dp)
                        staged.append(dp)

        return {
            "study_code": study_code,
            "staged_dir": dest_dir,
            "files_staged": len(staged),
        }

    def archive_study(self, study_code: str) -> Dict[str, Any]:
        """Archive local study outputs to external Data Vault."""
        if not self.is_vault_connected() or not self.vault_root:
            raise RuntimeError("Data Vault is disconnected. Cannot archive.")

        dest_dir = os.path.join(self.vault_root, "studies", study_code)
        os.makedirs(dest_dir, exist_ok=True)

        archived = []
        # Copy from review
        for f in glob.glob(os.path.join(self.review_dir, f"{study_code}*")):
            if os.path.isfile(f):
                dp = os.path.join(dest_dir, os.path.basename(f))
                shutil.copy2(f, dp)
                archived.append(dp)

        return {
            "study_code": study_code,
            "vault_dir": dest_dir,
            "files_archived": len(archived),
        }

    def verify_study_checksums(self, study_code: str) -> Dict[str, Any]:
        """Compare checksums between local files and external vault files."""
        tree = self.browse_study_tree(study_code)
        local_map = {f["name"]: f["path"] for f in tree["local_files"]}
        vault_map = {f["name"]: f["path"] for f in tree["vault_files"]}

        common_files = set(local_map.keys()) & set(vault_map.keys())
        results = []
        all_match = True

        for fn in sorted(common_files):
            lp = local_map[fn]
            vp = vault_map[fn]
            lh = compute_hash(lp)
            vh = compute_hash(vp)
            match = (lh == vh)
            if not match:
                all_match = False
            results.append({
                "filename": fn,
                "local_hash": lh,
                "vault_hash": vh,
                "match": match,
            })

        return {
            "study_code": study_code,
            "common_files_count": len(common_files),
            "all_match": all_match and len(common_files) > 0,
            "files": results,
        }

    def clean_staging(self, study_code: str) -> Dict[str, Any]:
        """Clean local staging directory for a specific study."""
        stg_dir = os.path.join(self.staging_dir, study_code)
        reclaimed = 0
        if os.path.isdir(stg_dir):
            for root, _, files in os.walk(stg_dir):
                for f in files:
                    reclaimed += os.path.getsize(os.path.join(root, f))
            shutil.rmtree(stg_dir, ignore_errors=True)

        return {
            "study_code": study_code,
            "reclaimed_bytes": reclaimed,
            "reclaimed_mb": round(reclaimed / (1024**2), 2),
        }

    def delete_study(self, study_code: str, target: str = "local") -> Dict[str, Any]:
        """Safely delete study from local workspace, staging, or vault (requires explicit target)."""
        deleted_count = 0
        if target in ("local", "all"):
            for f in glob.glob(os.path.join(self.review_dir, f"{study_code}*")):
                if os.path.isfile(f):
                    os.remove(f)
                    deleted_count += 1
            stg = os.path.join(self.staging_dir, study_code)
            if os.path.isdir(stg):
                shutil.rmtree(stg, ignore_errors=True)
                deleted_count += 1

        if target in ("vault", "all") and self.is_vault_connected() and self.vault_root:
            for sub in ("studies", "archive", "processed_mri"):
                vp = os.path.join(self.vault_root, sub, study_code)
                if os.path.isdir(vp):
                    shutil.rmtree(vp, ignore_errors=True)
                    deleted_count += 1

        return {
            "study_code": study_code,
            "target": target,
            "items_removed": deleted_count,
        }

    # =========================================================================
    # Granular Category & Filesystem Exploration Engine
    # =========================================================================

    def get_categories(self) -> Dict[str, Dict[str, Any]]:
        """Return all managed storage categories with resolved absolute paths and health."""
        vault_p = self.vault_root or ("/Volumes/Percival/PERCIVAL_VAULT" if os.path.exists("/Volumes/Percival") else "")
        categories = {
            "working": {
                "name": "Working Directory",
                "desc": "Active fast Mac NVMe SSD workspace",
                "path": self.base_dir,
                "icon": "folder"
            },
            "vault": {
                "name": "External Data Vault",
                "desc": "Permanent external storage archive",
                "path": vault_p,
                "icon": "hard-drive"
            },
            "originals": {
                "name": "MRI Originals",
                "desc": "Raw source DICOM / NIfTI scans",
                "path": os.path.join(self.base_dir, "data"),
                "icon": "database"
            },
            "imported": {
                "name": "Imported MRI",
                "desc": "De-identified staged MRI examinations",
                "path": os.path.join(self.app_data_dir, "import_src"),
                "icon": "inbox"
            },
            "processed": {
                "name": "Processed MRI",
                "desc": "FreeSurfer cortical surfaces and segmentations",
                "path": os.path.join(self.base_dir, "subjects"),
                "icon": "layers"
            },
            "albus": {
                "name": "ALBUS Outputs",
                "desc": "Sulcal deformation and Darboux geometric profiles",
                "path": os.path.join(self.base_dir, "review"),
                "icon": "cpu"
            },
            "lumos": {
                "name": "LUMOS Outputs",
                "desc": "Convolutional neural network inference & heatmaps",
                "path": os.path.join(self.base_dir, "unified_engine", "percival"),
                "icon": "eye"
            },
            "nox": {
                "name": "NOX Outputs",
                "desc": "Epistemic uncertainty maps & spatial tensors",
                "path": os.path.join(self.base_dir, "results", "nox"),
                "icon": "shield"
            },
            "pensieve": {
                "name": "Pensieve Core Memory",
                "desc": "SQLite database snapshots & clinical ledgers",
                "path": os.path.join(self.app_data_dir, "pensieve_snapshots"),
                "icon": "archive"
            },
            "models": {
                "name": "Models & Checkpoints",
                "desc": "Neural network weights & calibrated checkpoints",
                "path": os.path.join(self.base_dir, "unified_engine", "models"),
                "icon": "box"
            },
            "reports": {
                "name": "Reports & Exports",
                "desc": "Clinical PDFs and Excel spreadsheets",
                "path": os.path.join(self.base_dir, "results"),
                "icon": "file-text"
            },
            "staging": {
                "name": "Staging Buffer",
                "desc": "Active multi-study staging buffers",
                "path": self.staging_dir,
                "icon": "clock"
            },
            "scratch": {
                "name": "Temporary Scratch",
                "desc": "Intermediate matrices, resamplings, and logs",
                "path": os.path.join(self.app_data_dir, "scratch"),
                "icon": "trash-2"
            },
            "backups": {
                "name": "System Backups",
                "desc": "Pre-mission backups & pipeline versions",
                "path": os.path.join(self.app_data_dir, "pipeline_backups"),
                "icon": "refresh-cw"
            },
            "recovery": {
                "name": "Recovery Center",
                "desc": "Transactional ledgers, jobs, and quarantine",
                "path": self.app_data_dir,
                "icon": "life-buoy"
            }
        }

        # Annotate status
        for k, v in categories.items():
            p = v["path"]
            exists = bool(p and os.path.exists(p))
            v["exists"] = exists
            if exists:
                try:
                    usage = shutil.disk_usage(p)
                    v["free_gb"] = round(usage.free / (1024**3), 1)
                    v["writable"] = os.access(p, os.W_OK)
                except Exception:
                    v["free_gb"] = 0.0
                    v["writable"] = False
            else:
                v["free_gb"] = 0.0
                v["writable"] = False

        return categories

    def browse_category_path(self, category_key: str, subpath: str = "", search: str = "", sort_by: str = "name", sort_dir: str = "asc") -> Dict[str, Any]:
        """Browse files and folders inside a managed category path with search and sorting."""
        cats = self.get_categories()
        if category_key not in cats:
            return {"ok": False, "error": f"Unknown category '{category_key}'"}

        cat_info = cats[category_key]
        root_dir = cat_info["path"]
        if not root_dir or not os.path.exists(root_dir):
            return {
                "ok": True,
                "category": category_key,
                "category_name": cat_info["name"],
                "path": root_dir,
                "exists": False,
                "items": [],
                "error": "Directory does not exist on disk"
            }

        # Resolve subpath safely
        clean_sub = os.path.normpath(subpath).lstrip("/")
        if clean_sub == "." or not clean_sub:
            target_dir = root_dir
        else:
            target_dir = os.path.normpath(os.path.join(root_dir, clean_sub))

        # Security containment check
        try:
            if not os.path.commonpath([root_dir, target_dir]) == root_dir:
                return {"ok": False, "error": "Access denied: path traversal attempt outside category root"}
        except ValueError:
            return {"ok": False, "error": "Invalid path traversal"}

        if not os.path.isdir(target_dir):
            return {"ok": False, "error": f"Not a directory: {target_dir}"}

        entries = []
        try:
            with os.scandir(target_dir) as it:
                for entry in it:
                    if entry.name.startswith(".") and entry.name != ".percival_vault_id":
                        continue
                    if search and search.lower() not in entry.name.lower():
                        continue
                    try:
                        stat = entry.stat()
                        is_dir = entry.is_dir()
                        size = 0 if is_dir else stat.st_size
                        mtime = stat.st_mtime
                        mtime_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
                        
                        # Size format
                        if is_dir:
                            size_str = "Folder"
                        elif size < 1024:
                            size_str = f"{size} B"
                        elif size < 1024**2:
                            size_str = f"{size / 1024:.1f} KB"
                        elif size < 1024**3:
                            size_str = f"{size / (1024**2):.1f} MB"
                        else:
                            size_str = f"{size / (1024**3):.2f} GB"

                        entries.append({
                            "name": entry.name,
                            "path": entry.path,
                            "rel_path": os.path.relpath(entry.path, root_dir),
                            "is_dir": is_dir,
                            "size": size,
                            "size_str": size_str,
                            "mtime": mtime,
                            "mtime_str": mtime_str,
                            "writable": os.access(entry.path, os.W_OK),
                        })
                    except (PermissionError, OSError):
                        continue
        except Exception as e:
            return {"ok": False, "error": f"Failed reading directory: {str(e)}"}

        # Sorting
        reverse = (sort_dir.lower() == "desc")
        if sort_by == "size":
            entries.sort(key=lambda x: (not x["is_dir"], x["size"]), reverse=reverse)
        elif sort_by == "mtime":
            entries.sort(key=lambda x: x["mtime"], reverse=reverse)
        else: # name
            entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()), reverse=reverse)

        # Parent directory
        parent_sub = os.path.dirname(clean_sub) if clean_sub and clean_sub != "." else None

        return {
            "ok": True,
            "category": category_key,
            "category_name": cat_info["name"],
            "root_path": root_dir,
            "current_path": target_dir,
            "current_subpath": clean_sub if clean_sub != "." else "",
            "parent_subpath": parent_sub,
            "total_items": len(entries),
            "items": entries
        }

    def copy_item(self, src: str, dst_dir: str, conflict_mode: str = "keep_both") -> Dict[str, Any]:
        """Copy a file or directory with conflict handling (skip, keep_both, replace)."""
        src = os.path.abspath(src)
        dst_dir = os.path.abspath(dst_dir)
        if not os.path.exists(src):
            return {"ok": False, "error": f"Source does not exist: {src}"}
        if not os.path.isdir(dst_dir):
            return {"ok": False, "error": f"Destination directory does not exist: {dst_dir}"}

        basename = os.path.basename(src)
        target_path = os.path.join(dst_dir, basename)

        if os.path.exists(target_path):
            if conflict_mode == "skip":
                return {"ok": True, "skipped": True, "target_path": target_path}
            elif conflict_mode == "keep_both":
                name, ext = os.path.splitext(basename)
                if basename.endswith(".nii.gz"):
                    name = basename[:-7]
                    ext = ".nii.gz"
                ts = time.strftime("%Y%m%d_%H%M%S")
                target_path = os.path.join(dst_dir, f"{name}_copy_{ts}{ext}")
            elif conflict_mode == "replace":
                if os.path.isdir(target_path):
                    shutil.rmtree(target_path, ignore_errors=True)
                else:
                    os.remove(target_path)

        engine = get_transfer_engine(os.path.join(self.base_dir, "app_data", "transfers"))
        try:
            ok, msg, p_info = engine.transfer_path(
                src=src,
                dst=target_path,
                operation="copy",
                verify_sha=True,
                preserve_source=True
            )
            if not ok:
                return {"ok": False, "error": f"Copy failed: {msg}"}
            return {
                "ok": True,
                "source": src,
                "target_path": target_path,
                "bytes": p_info.get("completed_bytes", 0),
                "sha256": p_info.get("verification_status")
            }
        except Exception as e:
            return {"ok": False, "error": f"Copy failed: {str(e)}"}

    def move_item(self, src: str, dst_dir: str, conflict_mode: str = "keep_both") -> Dict[str, Any]:
        """Move a file or directory with verified destination and conflict handling."""
        src = os.path.abspath(src)
        dst_dir = os.path.abspath(dst_dir)
        if not os.path.exists(src):
            return {"ok": False, "error": f"Source does not exist: {src}"}
        if not os.path.isdir(dst_dir):
            return {"ok": False, "error": f"Destination directory does not exist: {dst_dir}"}

        basename = os.path.basename(src)
        target_path = os.path.join(dst_dir, basename)

        if os.path.exists(target_path):
            if conflict_mode == "skip":
                return {"ok": True, "skipped": True, "target_path": target_path}
            elif conflict_mode == "keep_both":
                name, ext = os.path.splitext(basename)
                if basename.endswith(".nii.gz"):
                    name = basename[:-7]
                    ext = ".nii.gz"
                ts = time.strftime("%Y%m%d_%H%M%S")
                target_path = os.path.join(dst_dir, f"{name}_moved_{ts}{ext}")
            elif conflict_mode == "replace":
                if os.path.isdir(target_path):
                    shutil.rmtree(target_path, ignore_errors=True)
                else:
                    os.remove(target_path)

        engine = get_transfer_engine(os.path.join(self.base_dir, "app_data", "transfers"))
        try:
            ok, msg, p_info = engine.transfer_path(
                src=src,
                dst=target_path,
                operation="move",
                verify_sha=True,
                preserve_source=False
            )
            if not ok:
                return {"ok": False, "error": f"Move failed: {msg}"}
            return {"ok": True, "source": src, "target_path": target_path, "bytes": p_info.get("completed_bytes", 0)}
        except Exception as e:
            return {"ok": False, "error": f"Move failed: {str(e)}"}

    def rename_item(self, path: str, new_name: str) -> Dict[str, Any]:
        """Rename an item within its directory."""
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return {"ok": False, "error": f"Item does not exist: {path}"}

        clean_name = os.path.basename(new_name.strip())
        if not clean_name or "/" in clean_name or "\\" in clean_name:
            return {"ok": False, "error": "Invalid name"}

        parent = os.path.dirname(path)
        target = os.path.join(parent, clean_name)
        if os.path.exists(target):
            return {"ok": False, "error": f"An item named '{clean_name}' already exists"}

        try:
            os.rename(path, target)
            return {"ok": True, "old_path": path, "new_path": target, "new_name": clean_name}
        except Exception as e:
            return {"ok": False, "error": f"Rename failed: {str(e)}"}

    def create_directory(self, parent_dir: str, dir_name: str) -> Dict[str, Any]:
        """Create a new subdirectory safely."""
        parent_dir = os.path.abspath(parent_dir)
        if not os.path.isdir(parent_dir):
            return {"ok": False, "error": f"Parent directory does not exist: {parent_dir}"}

        clean_name = os.path.basename(dir_name.strip())
        if not clean_name or "/" in clean_name or "\\" in clean_name:
            return {"ok": False, "error": "Invalid folder name"}

        target = os.path.join(parent_dir, clean_name)
        if os.path.exists(target):
            return {"ok": False, "error": f"Folder '{clean_name}' already exists"}

        try:
            os.makedirs(target, exist_ok=False)
            return {"ok": True, "path": target, "name": clean_name}
        except Exception as e:
            return {"ok": False, "error": f"Folder creation failed: {str(e)}"}

    def delete_item(self, path: str, confirm: bool = False) -> Dict[str, Any]:
        """Delete an item with strict safety guards."""
        if not confirm:
            return {"ok": False, "error": "Deletion requires explicit confirmation"}

        path = os.path.abspath(path)
        if not os.path.exists(path):
            return {"ok": False, "error": f"Path does not exist: {path}"}

        # Absolute protection rules
        protected = ["/", "/Users", "/Applications", "/Volumes", os.path.expanduser("~"), self.base_dir]
        if path in protected or os.path.dirname(path) in ("/", "/Users"):
            return {"ok": False, "error": "Refused: Protected critical directory cannot be deleted"}

        # Protected files
        if os.path.basename(path) in ("pensieve_core.db", "identity_vault.enc", "identity_vault.json"):
            return {"ok": False, "error": "Refused: Live Pensieve database or Identity Vault cannot be deleted"}

        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return {"ok": True, "deleted_path": path}
        except Exception as e:
            return {"ok": False, "error": f"Delete failed: {str(e)}"}

    def archive_entry(self, src: str, vault_category: str = "archive") -> Dict[str, Any]:
        """Copy item to External Data Vault with SHA-256 verification."""
        if not self.is_vault_connected() or not self.vault_root:
            return {"ok": False, "error": "External Data Vault is disconnected or not configured"}

        target_dir = os.path.join(self.vault_root, vault_category)
        os.makedirs(target_dir, exist_ok=True)

        res = self.copy_item(src, target_dir, conflict_mode="keep_both")
        if not res.get("ok"):
            return res

        # Verify checksum if file
        target_file = res["target_path"]
        if os.path.isfile(src) and os.path.isfile(target_file):
            src_sha = compute_hash(src)
            dst_sha = compute_hash(target_file)
            if src_sha != dst_sha:
                os.remove(target_file)
                return {"ok": False, "error": "Checksum mismatch during vault archive - target removed"}
            res["sha256"] = src_sha
            res["verified"] = True

        return res

    def restore_entry(self, vault_path: str, local_dst_dir: str) -> Dict[str, Any]:
        """Restore item from External Data Vault to local SSD with verification."""
        if not os.path.exists(vault_path):
            return {"ok": False, "error": f"Vault path does not exist: {vault_path}"}
        os.makedirs(local_dst_dir, exist_ok=True)

        res = self.copy_item(vault_path, local_dst_dir, conflict_mode="keep_both")
        if not res.get("ok"):
            return res

        target_file = res["target_path"]
        if os.path.isfile(vault_path) and os.path.isfile(target_file):
            v_sha = compute_hash(vault_path)
            l_sha = compute_hash(target_file)
            if v_sha != l_sha:
                os.remove(target_file)
                return {"ok": False, "error": "Checksum mismatch during restore - target removed"}
            res["sha256"] = v_sha
            res["verified"] = True

        return res
