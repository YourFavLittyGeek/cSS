"""wizard.py - First-launch 6-step installation and configuration wizard engine for PERCIVAL.

Provides an automated onboarding, system inspection, storage topology setup,
external volume detection, legacy data discovery, migration planning,
and installation verification engine.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple


class SetupWizard:
    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)
        self.app_data_dir = os.path.join(self.base_dir, "app_data")
        os.makedirs(self.app_data_dir, exist_ok=True)
        self.state_file = os.path.join(self.app_data_dir, "wizard_state.json")
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "status": "not_started",
            "current_step": 1,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "steps": {
                "step1_system": None,
                "step2_storage": None,
                "step3_volumes": None,
                "step4_legacy_scan": None,
                "step5_migration_plan": None,
                "step6_finalization": None,
            },
        }

    def _save_state(self) -> None:
        self.state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tmp = self.state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f, indent=2)
        os.replace(tmp, self.state_file)

    def is_completed(self) -> bool:
        return self.state.get("status") == "completed"

    def get_state(self) -> Dict[str, Any]:
        return dict(self.state)

    def reset(self) -> Dict[str, Any]:
        if os.path.exists(self.state_file):
            try:
                os.remove(self.state_file)
            except Exception:
                pass
        self.state = self._load_state()
        self._save_state()
        return self.state

    # -------------------------------------------------------------------------
    # STEP 1: System Inspection & Prerequisite Validation
    # -------------------------------------------------------------------------
    def step1_inspect_system(self) -> Dict[str, Any]:
        system_info: Dict[str, Any] = {
            "os_name": platform.system(),
            "os_release": platform.release(),
            "mac_ver": platform.mac_ver()[0] if hasattr(platform, "mac_ver") else "",
            "architecture": platform.machine(),
            "is_apple_silicon": platform.machine().lower() in ("arm64", "aarch64"),
            "cpu_count": os.cpu_count() or 1,
            "ram_total_gb": 0.0,
            "recommended_concurrency": 1,
            "ssd_total_gb": 0.0,
            "ssd_free_gb": 0.0,
            "ssd_warning": False,
            "freesurfer": {
                "installed": False,
                "home": "",
                "license_valid": False,
                "recon_all_found": False,
                "mri_synthseg_found": False,
                "version": "",
            },
            "python_env": {
                "executable": sys.executable,
                "version": sys.version.split()[0],
                "dependencies": {},
            },
            "binaries": {
                "dcm2niix": shutil.which("dcm2niix") is not None,
            },
            "ready": True,
            "warnings": [],
            "blockers": [],
        }

        # RAM detection on macOS via sysctl
        try:
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            total_bytes = int(out)
            system_info["ram_total_gb"] = round(total_bytes / (1024**3), 1)
        except Exception:
            try:
                import psutil  # type: ignore
                system_info["ram_total_gb"] = round(psutil.virtual_memory().total / (1024**3), 1)
            except Exception:
                system_info["ram_total_gb"] = 16.0  # safe fallback assumption

        # Concurrency recommendation based on RAM and CPU
        ram = system_info["ram_total_gb"]
        cpus = system_info["cpu_count"]
        if ram >= 32.0 and cpus >= 8:
            system_info["recommended_concurrency"] = min(4, cpus // 2)
        elif ram >= 16.0 and cpus >= 4:
            system_info["recommended_concurrency"] = min(2, cpus // 2)
        else:
            system_info["recommended_concurrency"] = 1

        # Disk space for Mac root SSD
        try:
            usage = shutil.disk_usage(self.base_dir)
            system_info["ssd_total_gb"] = round(usage.total / (1024**3), 1)
            system_info["ssd_free_gb"] = round(usage.free / (1024**3), 1)
            if system_info["ssd_free_gb"] < 50.0:
                system_info["ssd_warning"] = True
                system_info["warnings"].append(
                    f"Low Mac SSD free space: {system_info['ssd_free_gb']} GB available (< 50 GB recommended)."
                )
        except Exception as e:
            system_info["warnings"].append(f"Failed to query SSD disk usage: {e}")

        # FreeSurfer inspection
        fs_home = os.environ.get("FREESURFER_HOME", "")
        if not fs_home or not os.path.isdir(fs_home):
            for candidate in ["/Applications/freesurfer", "/usr/local/freesurfer", os.path.expanduser("~/freesurfer")]:
                if os.path.isdir(candidate):
                    fs_home = candidate
                    break

        if fs_home and os.path.isdir(fs_home):
            system_info["freesurfer"]["home"] = fs_home
            system_info["freesurfer"]["installed"] = True
            recon_all = os.path.join(fs_home, "bin", "recon-all")
            synthseg = os.path.join(fs_home, "bin", "mri_synthseg")
            system_info["freesurfer"]["recon_all_found"] = os.path.isfile(recon_all) and os.access(recon_all, os.X_OK)
            system_info["freesurfer"]["mri_synthseg_found"] = os.path.isfile(synthseg) and os.access(synthseg, os.X_OK)
            lic = os.path.join(fs_home, "license.txt")
            if os.path.isfile(lic) and os.path.getsize(lic) > 10:
                system_info["freesurfer"]["license_valid"] = True
            else:
                system_info["warnings"].append("FreeSurfer license.txt missing or empty in FREESURFER_HOME.")
        else:
            system_info["warnings"].append("FreeSurfer installation not found in FREESURFER_HOME or standard paths.")

        # Python packages inspection
        required_pkgs = ["nibabel", "scipy", "sklearn", "torch", "pandas", "numpy"]
        for pkg in required_pkgs:
            try:
                mod = __import__(pkg)
                ver = getattr(mod, "__version__", "installed")
                system_info["python_env"]["dependencies"][pkg] = {"installed": True, "version": ver}
            except ImportError:
                system_info["python_env"]["dependencies"][pkg] = {"installed": False, "version": None}
                system_info["warnings"].append(f"Optional or auxiliary Python module '{pkg}' not installed.")

        if not system_info["binaries"]["dcm2niix"]:
            system_info["warnings"].append("dcm2niix binary not found in PATH; DICOM to NIfTI conversion will require manual entry.")

        # Persist step result
        self.state["steps"]["step1_system"] = system_info
        if self.state["current_step"] == 1:
            self.state["current_step"] = 2
        self.state["status"] = "in_progress"
        self._save_state()
        return system_info

    # -------------------------------------------------------------------------
    # STEP 2: Storage Topology & Workspace Configuration
    # -------------------------------------------------------------------------
    def step2_configure_storage(
        self,
        local_workspace: Optional[str] = None,
        vault_mount: Optional[str] = None,
        backup_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        local_ws = os.path.abspath(os.path.expanduser(local_workspace or self.base_dir))
        vault_path = os.path.abspath(os.path.expanduser(vault_mount)) if vault_mount else None
        b_dir = os.path.abspath(os.path.expanduser(backup_dir)) if backup_dir else os.path.join(local_ws, "backups")

        cfg: Dict[str, Any] = {
            "local_workspace": local_ws,
            "vault_mount": vault_path,
            "backup_dir": b_dir,
            "local_workspace_writable": False,
            "vault_mount_writable": False,
            "backup_dir_writable": False,
            "errors": [],
        }

        # Check local workspace
        try:
            os.makedirs(local_ws, exist_ok=True)
            test_file = os.path.join(local_ws, ".percival_write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            cfg["local_workspace_writable"] = True
        except Exception as e:
            cfg["errors"].append(f"Local workspace '{local_ws}' is not writable: {e}")

        # Check vault mount if specified
        if vault_path:
            if os.path.exists(vault_path):
                try:
                    test_file = os.path.join(vault_path, ".percival_write_test")
                    with open(test_file, "w") as f:
                        f.write("test")
                    os.remove(test_file)
                    cfg["vault_mount_writable"] = True
                except Exception as e:
                    cfg["errors"].append(f"Data Vault path '{vault_path}' exists but is not writable: {e}")
            else:
                cfg["errors"].append(f"Data Vault path '{vault_path}' does not exist.")

        # Check backup dir
        try:
            os.makedirs(b_dir, exist_ok=True)
            test_file = os.path.join(b_dir, ".percival_write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            cfg["backup_dir_writable"] = True
        except Exception as e:
            cfg["errors"].append(f"Backup directory '{b_dir}' is not writable: {e}")

        cfg["valid"] = len(cfg["errors"]) == 0
        self.state["steps"]["step2_storage"] = cfg
        if cfg["valid"] and self.state["current_step"] == 2:
            self.state["current_step"] = 3
        self._save_state()
        return cfg

    # -------------------------------------------------------------------------
    # STEP 3: External Volume Detection & Setup
    # -------------------------------------------------------------------------
    def step3_detect_volumes(self) -> Dict[str, Any]:
        volumes_root = "/Volumes"
        detected_volumes: List[Dict[str, Any]] = []

        if os.path.exists(volumes_root):
            try:
                for entry in sorted(os.listdir(volumes_root)):
                    vol_path = os.path.join(volumes_root, entry)
                    if not os.path.isdir(vol_path) or os.path.islink(vol_path):
                        continue
                    # Exclude the root Macintosh HD mount loop if present
                    if os.path.realpath(vol_path) == "/":
                        continue

                    vol_info: Dict[str, Any] = {
                        "name": entry,
                        "mount_point": vol_path,
                        "filesystem": "Unknown",
                        "uuid": "",
                        "total_gb": 0.0,
                        "free_gb": 0.0,
                        "writable": False,
                        "is_vault_candidate": False,
                    }

                    # Query diskutil info if on macOS
                    try:
                        out = subprocess.check_output(["diskutil", "info", vol_path], text=True, stderr=subprocess.DEVNULL)
                        for line in out.splitlines():
                            line_s = line.strip()
                            if line_s.startswith("Type (Bundle):") or line_s.startswith("File System Personality:"):
                                vol_info["filesystem"] = line_s.split(":", 1)[1].strip()
                            elif line_s.startswith("Volume UUID:"):
                                vol_info["uuid"] = line_s.split(":", 1)[1].strip()
                    except Exception:
                        pass

                    # Fallback uuid from marker file if present
                    uuid_file = os.path.join(vol_path, ".percival_vault_uuid")
                    if not vol_info["uuid"] and os.path.exists(uuid_file):
                        try:
                            with open(uuid_file, "r") as f:
                                vol_info["uuid"] = f.read().strip()
                        except Exception:
                            pass

                    # Capacity and writability
                    try:
                        usage = shutil.disk_usage(vol_path)
                        vol_info["total_gb"] = round(usage.total / (1024**3), 1)
                        vol_info["free_gb"] = round(usage.free / (1024**3), 1)
                        test_file = os.path.join(vol_path, ".percival_detect_test")
                        with open(test_file, "w") as f:
                            f.write("ok")
                        os.remove(test_file)
                        vol_info["writable"] = True
                    except Exception:
                        vol_info["writable"] = False

                    # Identify candidate
                    if "PERCIVAL" in entry.upper() or "VAULT" in entry.upper() or vol_info["free_gb"] > 100.0:
                        vol_info["is_vault_candidate"] = True

                    detected_volumes.append(vol_info)
            except Exception as e:
                pass

        result = {
            "count": len(detected_volumes),
            "volumes": detected_volumes,
            "has_external": len(detected_volumes) > 0,
        }
        self.state["steps"]["step3_volumes"] = result
        if self.state["current_step"] == 3:
            self.state["current_step"] = 4
        self._save_state()
        return result

    # -------------------------------------------------------------------------
    # STEP 4: Legacy Research Data Discovery Scan
    # -------------------------------------------------------------------------
    def step4_scan_legacy_data(self, search_roots: Optional[List[str]] = None) -> Dict[str, Any]:
        """Perform a strictly read-only discovery scan for existing Percival / cSS datasets."""
        roots = search_roots or [
            self.base_dir,
            os.path.expanduser("~/percival_workspace"),
            os.path.expanduser("~/cSS_pipeline"),
            os.path.expanduser("~/css_project"),
            os.path.expanduser("~/cSS_experimental"),
        ]

        discovered: List[Dict[str, Any]] = []
        total_discovered_bytes = 0

        for r in roots:
            abs_r = os.path.abspath(os.path.expanduser(r))
            if not os.path.isdir(abs_r):
                continue
            base_depth = abs_r.rstrip(os.sep).count(os.sep)

            try:
                for root_dir, dirs, files in os.walk(abs_r):
                    current_depth = root_dir.rstrip(os.sep).count(os.sep) - base_depth
                    if current_depth > 4:
                        dirs.clear()
                        continue
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("Library", "Trash", "node_modules", "DerivedData", "build", "dist", ".percival_backup")]

                    # 1. Look for Pensieve database
                    for f in files:
                        if f in ("pensieve.db", "pensieve_core.db"):
                            p = os.path.join(root_dir, f)
                            sz = os.path.getsize(p)
                            total_discovered_bytes += sz
                            discovered.append({
                                "path": p,
                                "type": "pensieve_db",
                                "size_bytes": sz,
                                "size_mb": round(sz / (1024**2), 2),
                                "modified": os.path.getmtime(p),
                            })
                        elif f in ("patients.json", "names.csv"):
                            p = os.path.join(root_dir, f)
                            sz = os.path.getsize(p)
                            total_discovered_bytes += sz
                            discovered.append({
                                "path": p,
                                "type": "legacy_registry",
                                "size_bytes": sz,
                                "size_mb": round(sz / (1024**2), 2),
                                "modified": os.path.getmtime(p),
                            })
                        elif f.endswith("_candidates.csv"):
                            p = os.path.join(root_dir, f)
                            sz = os.path.getsize(p)
                            total_discovered_bytes += sz
                            discovered.append({
                                "path": p,
                                "type": "candidate_records",
                                "size_bytes": sz,
                                "size_mb": round(sz / (1024**2), 2),
                                "modified": os.path.getmtime(p),
                            })
                        elif f.endswith(".nii") or f.endswith(".nii.gz"):
                            # Avoid enumerating millions of individual files; detect study root
                            if "SWI" in f.upper() or "BRAIN" in f.upper():
                                p = os.path.join(root_dir, f)
                                sz = os.path.getsize(p)
                                total_discovered_bytes += sz
                                discovered.append({
                                    "path": p,
                                    "type": "nifti_image",
                                    "size_bytes": sz,
                                    "size_mb": round(sz / (1024**2), 2),
                                    "modified": os.path.getmtime(p),
                                })
            except Exception:
                continue

        result = {
            "total_items": len(discovered),
            "total_discovered_gb": round(total_discovered_bytes / (1024**3), 2),
            "items": discovered[:200],  # cap at 200 items for state summary
        }
        self.state["steps"]["step4_legacy_scan"] = result
        if self.state["current_step"] == 4:
            self.state["current_step"] = 5
        self._save_state()
        return result

    # -------------------------------------------------------------------------
    # STEP 5: Migration Plan Generation
    # -------------------------------------------------------------------------
    def step5_generate_migration_plan(
        self,
        active_retention_days: int = 30,
        target_vault: Optional[str] = None,
    ) -> Dict[str, Any]:
        scan_res = self.state["steps"].get("step4_legacy_scan") or self.step4_scan_legacy_data()
        items = scan_res.get("items", [])
        now = time.time()
        retention_sec = active_retention_days * 86400

        stage_local: List[Dict[str, Any]] = []
        archive_vault: List[Dict[str, Any]] = []
        import_pensieve: List[Dict[str, Any]] = []
        recoverable_bytes = 0

        for it in items:
            itype = it["type"]
            age_sec = now - it.get("modified", 0)

            if itype in ("pensieve_db", "candidate_records", "legacy_registry"):
                import_pensieve.append(it)
            elif itype == "nifti_image":
                if age_sec <= retention_sec:
                    stage_local.append(it)
                else:
                    archive_vault.append(it)
                    recoverable_bytes += it.get("size_bytes", 0)
            else:
                archive_vault.append(it)
                recoverable_bytes += it.get("size_bytes", 0)

        plan = {
            "active_retention_days": active_retention_days,
            "target_vault": target_vault or self.state["steps"].get("step2_storage", {}).get("vault_mount"),
            "stage_local_count": len(stage_local),
            "archive_vault_count": len(archive_vault),
            "import_pensieve_count": len(import_pensieve),
            "estimated_space_reclaimed_gb": round(recoverable_bytes / (1024**3), 2),
            "stage_local_samples": stage_local[:5],
            "archive_vault_samples": archive_vault[:5],
            "import_pensieve_samples": import_pensieve[:5],
        }

        self.state["steps"]["step5_migration_plan"] = plan
        if self.state["current_step"] == 5:
            self.state["current_step"] = 6
        self._save_state()
        return plan

    # -------------------------------------------------------------------------
    # STEP 6: Installation Verification & State Persistence
    # -------------------------------------------------------------------------
    def step6_finalize(self, config_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        overrides = config_overrides or {}

        # Ensure all required subdirectories exist
        dirs_to_create = [
            os.path.join(self.base_dir, "app_data"),
            os.path.join(self.base_dir, "app_data", "identity"),
            os.path.join(self.base_dir, "app_data", "logs"),
            os.path.join(self.base_dir, "app_data", "staging"),
            os.path.join(self.base_dir, "app_data", "scratch"),
            os.path.join(self.base_dir, "private"),
            os.path.join(self.base_dir, "review"),
            os.path.join(self.base_dir, "backups"),
        ]
        for d in dirs_to_create:
            os.makedirs(d, exist_ok=True)

        # Write or update settings.json
        settings_path = os.path.join(self.base_dir, "app_data", "settings.json")
        current_settings: Dict[str, Any] = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r") as f:
                    current_settings = json.load(f)
            except Exception:
                pass

        # Default configuration: app_lock_enabled is False (no password required)
        current_settings.setdefault("app_lock_enabled", False)
        current_settings.setdefault("identity_mode", "standard")
        current_settings.setdefault("awake", True)
        current_settings.setdefault("theme", "dark")
        current_settings.setdefault("storage_policy", {
            "retention_scratch_days": 7,
            "retention_failed_days": 14,
            "retention_cache_days": 30,
            "remove_local_mri_after_archive": False,
        })

        # Apply storage configuration from step 2 if available
        s2 = self.state["steps"].get("step2_storage") or {}
        if s2.get("vault_mount"):
            current_settings["vault_mount"] = s2["vault_mount"]
        if s2.get("backup_dir"):
            current_settings["backup_dir"] = s2["backup_dir"]

        current_settings.update(overrides)

        tmp_set = settings_path + ".tmp"
        with open(tmp_set, "w") as f:
            json.dump(current_settings, f, indent=2)
        os.replace(tmp_set, settings_path)

        # Mark wizard completed
        self.state["status"] = "completed"
        self.state["current_step"] = 6
        self.state["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.state["steps"]["step6_finalization"] = {
            "success": True,
            "settings_path": settings_path,
            "settings": current_settings,
        }
        self._save_state()

        return {
            "status": "completed",
            "message": "PERCIVAL setup wizard finalized successfully.",
            "settings": current_settings,
            "completed_at": self.state["completed_at"],
        }
