"""Automated targeted software and environment discovery service for PERCIVAL.

Mission ID: PERCIVAL-SETUP-REDESIGN-2026
"""

import os
import sys
import glob
import shutil
import platform
import subprocess
from typing import Dict, Any, List, Optional
from .models import InstallationCandidate
from .validators import (
    validate_python,
    validate_pipeline,
    validate_freesurfer,
    validate_license,
    validate_mri_tool,
    validate_workspace,
    validate_vault,
    validate_pensieve
)


class InstallationDiscoveryService:
    """Discovers available scientific software installations, environments, and storage topologies."""

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = os.path.abspath(workspace_root or os.path.expanduser("~/Percival_project"))

    def discover_system_info(self) -> Dict[str, Any]:
        """Collect non-destructive macOS host information."""
        total_ram_gb = 16.0
        try:
            r = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2)
            if r.returncode == 0 and r.stdout.strip():
                total_ram_gb = round(int(r.stdout.strip()) / (1024**3), 1)
        except Exception:
            pass

        ws_usage = shutil.disk_usage(self.workspace_root) if os.path.isdir(self.workspace_root) else shutil.disk_usage(os.path.expanduser("~"))
        free_ssd_gb = round(ws_usage.free / (1024**3), 1)
        total_ssd_gb = round(ws_usage.total / (1024**3), 1)

        return {
            "os_name": platform.system(),
            "os_version": platform.mac_ver()[0] or platform.release(),
            "architecture": platform.machine(),
            "cpu_brand": platform.processor() or "Apple Silicon",
            "total_ram_gb": total_ram_gb,
            "free_ssd_gb": free_ssd_gb,
            "total_ssd_gb": total_ssd_gb,
            "active_user": os.environ.get("USER", "unknown")
        }

    def discover_python_environments(self) -> List[InstallationCandidate]:
        """Targeted scan for viable Python 3.10+ environments."""
        candidates: List[InstallationCandidate] = []
        seen_paths = set()

        search_locations = [
            sys.executable,
            os.path.expanduser("~/miniforge3/envs/css/bin/python3"),
            os.path.expanduser("~/miniforge3/envs/percival/bin/python3"),
            os.path.expanduser("~/miniforge3/bin/python3"),
            os.path.expanduser("~/mambaforge/envs/css/bin/python3"),
            os.path.expanduser("~/miniconda3/envs/css/bin/python3"),
            os.path.expanduser("~/anaconda3/envs/css/bin/python3"),
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3"
        ]

        # Also search conda envs directory dynamically
        for base in [os.path.expanduser("~/miniforge3/envs"), os.path.expanduser("~/miniconda3/envs")]:
            if os.path.isdir(base):
                for d in os.listdir(base):
                    p_exe = os.path.join(base, d, "bin", "python3")
                    if os.path.isfile(p_exe):
                        search_locations.append(p_exe)

        for exe in search_locations:
            if not exe or not os.path.isfile(exe):
                continue
            real_exe = os.path.realpath(exe)
            if real_exe in seen_paths:
                continue
            seen_paths.add(real_exe)

            val = validate_python(real_exe)
            is_active = (real_exe == os.path.realpath(sys.executable))
            is_css_env = "envs/css" in real_exe or "envs/percival" in real_exe

            cand = InstallationCandidate(
                component_id="python",
                name=f"Python {val.get('version', '')} ({'Active' if is_active else os.path.basename(os.path.dirname(os.path.dirname(real_exe)))})",
                path=real_exe,
                executable_path=real_exe,
                version=val.get("version", "unknown"),
                is_valid=val.get("ok", False),
                validation_message=val.get("error", "Valid scientific environment") if not val.get("ok") else "All required packages present",
                is_preferred=val.get("ok", False) and (is_active or is_css_env),
                discovery_method="active_runtime" if is_active else "conda_env",
                last_validated=os.path.getmtime(real_exe),
                details=val
            )
            candidates.append(cand)

        # Sort so preferred valid candidates come first
        candidates.sort(key=lambda c: (c.is_preferred, c.is_valid), reverse=True)
        return candidates

    def discover_pipeline_installations(self) -> List[InstallationCandidate]:
        """Locate candidate PERCIVAL pipeline codebases and versions."""
        candidates: List[InstallationCandidate] = []
        seen = set()

        # Plausible pipeline directories
        search_dirs = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")),
            self.workspace_root,
            os.path.expanduser("~/Percival_project"),
            os.path.expanduser("~/css_project"),
            "/Applications/Percival Dev.app/Contents/Resources/pipeline",
            "/Applications/Percival.app/Contents/Resources/pipeline"
        ]

        for d in search_dirs:
            if not d or not os.path.isdir(d):
                continue
            real_d = os.path.realpath(d)
            if real_d in seen:
                continue
            seen.add(real_d)

            val = validate_pipeline(real_d)
            if val.get("ok"):
                is_active = (real_d == os.path.realpath(self.workspace_root) or "percival_code_only" in real_d)
                cand = InstallationCandidate(
                    component_id="pipeline",
                    name=f"PERCIVAL Pipeline {val.get('version', '')}",
                    path=real_d,
                    executable_path=val.get("entry_point"),
                    version=val.get("version", "v5.26"),
                    is_valid=True,
                    validation_message=f"{val.get('script_count', 0)} executable scripts verified",
                    is_preferred=is_active,
                    discovery_method="repository_root" if "percival_code_only" in real_d else "project_workspace",
                    last_validated=os.path.getmtime(real_d),
                    details=val
                )
                candidates.append(cand)

        candidates.sort(key=lambda c: (c.is_preferred, c.is_valid), reverse=True)
        return candidates

    def discover_freesurfer_installations(self) -> List[InstallationCandidate]:
        """Locate FreeSurfer installations across standard macOS directories."""
        candidates: List[InstallationCandidate] = []
        seen = set()

        search_dirs = []
        # Check /Applications/freesurfer*
        if os.path.isdir("/Applications"):
            for entry in os.listdir("/Applications"):
                if "freesurfer" in entry.lower():
                    search_dirs.append(os.path.join("/Applications", entry))
                    # Also check nested version dirs
                    sub = os.path.join("/Applications", entry)
                    if os.path.isdir(sub):
                        for s in os.listdir(sub):
                            search_dirs.append(os.path.join(sub, s))

        # Check environment variables
        env_fs = os.environ.get("FREESURFER_HOME")
        if env_fs:
            search_dirs.append(env_fs)

        search_dirs.extend([
            "/usr/local/freesurfer",
            "/opt/freesurfer",
            os.path.expanduser("~/freesurfer")
        ])

        for d in search_dirs:
            if not d or not os.path.isdir(d):
                continue
            real_d = os.path.realpath(d)
            if real_d in seen:
                continue
            seen.add(real_d)

            val = validate_freesurfer(real_d)
            if val.get("ok"):
                cand = InstallationCandidate(
                    component_id="freesurfer",
                    name=f"FreeSurfer ({os.path.basename(real_d)})",
                    path=real_d,
                    executable_path=os.path.join(real_d, "bin", "mri_synthseg"),
                    version=val.get("version", "v7+"),
                    is_valid=True,
                    validation_message="All core tools verified (mri_synthseg, mri_convert, mri_vol2vol)",
                    is_preferred=bool(val.get("major") and val["major"] >= 8),
                    discovery_method="standard_applications" if "/Applications" in real_d else "env_var",
                    last_validated=os.path.getmtime(real_d),
                    details=val
                )
                candidates.append(cand)

        candidates.sort(key=lambda c: (c.is_preferred, c.is_valid), reverse=True)
        return candidates

    def discover_freesurfer_licenses(self, fs_homes: Optional[List[str]] = None) -> List[InstallationCandidate]:
        """Find valid FreeSurfer license files on the Mac."""
        candidates: List[InstallationCandidate] = []
        seen = set()

        search_files = [
            os.path.expanduser("~/Downloads/license.txt"),
            os.path.expanduser("~/Downloads/.license"),
            os.path.expanduser("~/license.txt"),
            os.path.expanduser("~/.license"),
            os.environ.get("FS_LICENSE", "")
        ]

        if fs_homes:
            for fh in fs_homes:
                if fh and os.path.isdir(fh):
                    search_files.append(os.path.join(fh, "license.txt"))
                    search_files.append(os.path.join(fh, ".license"))

        # Also search ~/Downloads/*.txt for potential licenses
        dl_dir = os.path.expanduser("~/Downloads")
        if os.path.isdir(dl_dir):
            for f in os.listdir(dl_dir):
                if "license" in f.lower() and f.endswith(".txt"):
                    search_files.append(os.path.join(dl_dir, f))

        for f in search_files:
            if not f or not os.path.isfile(f):
                continue
            real_f = os.path.realpath(f)
            if real_f in seen:
                continue
            seen.add(real_f)

            val = validate_license(real_f)
            if val.get("ok"):
                cand = InstallationCandidate(
                    component_id="license",
                    name=f"License ({os.path.basename(real_f)})",
                    path=real_f,
                    version="Valid structure",
                    is_valid=True,
                    validation_message="Valid FreeSurfer license format",
                    is_preferred=True,
                    discovery_method="downloads_folder" if "Downloads" in real_f else "env_var",
                    last_validated=os.path.getmtime(real_f),
                    details=val
                )
                candidates.append(cand)

        return candidates

    def discover_mri_tools(self) -> Dict[str, InstallationCandidate]:
        """Check for essential MRI conversion and decompression tools."""
        tools = {}
        for t in ("dcm2niix", "dcmdjpeg"):
            val = validate_mri_tool(t)
            tools[t] = InstallationCandidate(
                component_id=t,
                name=f"MRI Tool: {t}",
                path=val.get("path") or "",
                executable_path=val.get("path"),
                version=val.get("version", "unknown"),
                is_valid=val.get("ok", False),
                validation_message=val.get("error", "Ready for DICOM ingestion") if not val.get("ok") else "Installed and responsive",
                is_preferred=val.get("ok", False),
                discovery_method="system_path",
                last_validated=0.0,
                details=val
            )
        return tools

    def discover_storage_topology(self) -> Dict[str, Any]:
        """Detect internal SSD workspace and external Data Vaults."""
        # 1. Internal SSD workspace validation
        ws_val = validate_workspace(self.workspace_root)
        ws_cand = InstallationCandidate(
            component_id="workspace",
            name="Fast Internal Mac NVMe SSD Workspace",
            path=self.workspace_root,
            version=f"{ws_val.get('free_gb', 0)} GB free",
            is_valid=ws_val.get("ok", False),
            validation_message=ws_val.get("warning") or ("Ready for staging and active processing" if ws_val.get("ok") else ws_val.get("error", "")),
            is_preferred=True,
            discovery_method="configured_project",
            details=ws_val
        )

        # 2. External Volumes & Vault discovery
        vault_candidates: List[InstallationCandidate] = []
        vol_root = "/Volumes"
        if os.path.isdir(vol_root):
            for v in sorted(os.listdir(vol_root)):
                if v.startswith(".") or v == "Macintosh HD":
                    continue
                mp = os.path.join(vol_root, v)
                if not os.path.isdir(mp):
                    continue

                # Check if volume hosts a PERCIVAL_VAULT
                vault_dir = os.path.join(mp, "PERCIVAL_VAULT")
                is_vault = os.path.isdir(vault_dir)
                target_p = vault_dir if is_vault else mp
                val_v = validate_vault(target_p)

                vault_cand = InstallationCandidate(
                    component_id="vault",
                    name=f"External Vault on {v}" if is_vault else f"External Volume: {v}",
                    path=target_p,
                    version=f"{val_v.get('free_gb', 0)} GB free",
                    is_valid=val_v.get("ok", False),
                    validation_message=f"Vault UUID: {val_v.get('vault_uuid', 'unassigned')} · {val_v.get('existing_studies_count', 0)} existing studies" if is_vault else "Ready to initialize PERCIVAL_VAULT",
                    is_preferred=is_vault,
                    discovery_method="mounted_volume",
                    details=val_v
                )
                vault_candidates.append(vault_cand)

        return {
            "workspace": ws_cand,
            "vaults": vault_candidates
        }

    def discover_pensieve_databases(self) -> List[InstallationCandidate]:
        """Find active and archived Pensieve provenance databases."""
        candidates: List[InstallationCandidate] = []
        search_paths = [
            os.path.join(self.workspace_root, "app_data", "pensieve.db"),
            os.path.expanduser("~/css_project/app_data/pensieve.db"),
            "/Volumes/Percival/PERCIVAL_VAULT/PENSIEVE/Database_Backups/pensieve_preclean_backup_20261123_013844.db"
        ]

        # Scan any backup directories in Vault
        vault_backups = "/Volumes/Percival/PERCIVAL_VAULT/PENSIEVE/Database_Backups"
        if os.path.isdir(vault_backups):
            for f in os.listdir(vault_backups):
                if f.endswith(".db"):
                    search_paths.append(os.path.join(vault_backups, f))

        seen = set()
        for p in search_paths:
            if not p or not os.path.isfile(p):
                continue
            real_p = os.path.realpath(p)
            if real_p in seen:
                continue
            seen.add(real_p)

            val = validate_pensieve(real_p)
            is_active = (real_p == os.path.realpath(os.path.join(self.workspace_root, "app_data", "pensieve.db")))
            cand = InstallationCandidate(
                component_id="pensieve",
                name="Active Pensieve Database" if is_active else f"Pensieve Backup ({os.path.basename(real_p)})",
                path=real_p,
                version=f"{val.get('table_count', 0)} tables · {val.get('studies_count', 0)} studies",
                is_valid=val.get("ok", False),
                validation_message="Integrity verified" if val.get("ok") else val.get("error", "Integrity error"),
                is_preferred=is_active,
                discovery_method="active_workspace" if is_active else "vault_backup",
                last_validated=os.path.getmtime(real_p),
                details=val
            )
            candidates.append(cand)

        return candidates

    def run_full_discovery(self) -> Dict[str, Any]:
        """Perform a comprehensive, non-destructive system discovery scan."""
        sys_info = self.discover_system_info()
        py_candidates = self.discover_python_environments()
        pipeline_candidates = self.discover_pipeline_installations()
        fs_candidates = self.discover_freesurfer_installations()
        lic_candidates = self.discover_freesurfer_licenses([c.path for c in fs_candidates])
        mri_tools = self.discover_mri_tools()
        storage = self.discover_storage_topology()
        pensieve = self.discover_pensieve_databases()

        # Discover preserved original MRI studies
        discovered_studies = []
        try:
            from ..study_workspace_manager import StudyWorkspaceManager
            swm = StudyWorkspaceManager(self.workspace_root, vault_root=self.vault_root)
            discovered_studies = swm.discover_source_studies()
        except Exception:
            discovered_studies = []

        return {
            "timestamp": os.path.getmtime(self.workspace_root) if os.path.isdir(self.workspace_root) else 0.0,
            "system": sys_info,
            "python": [c.to_dict() for c in py_candidates],
            "pipeline": [c.to_dict() for c in pipeline_candidates],
            "freesurfer": [c.to_dict() for c in fs_candidates],
            "licenses": [c.to_dict() for c in lic_candidates],
            "mri_tools": {k: v.to_dict() for k, v in mri_tools.items()},
            "storage": {
                "workspace": storage["workspace"].to_dict(),
                "vaults": [v.to_dict() for v in storage["vaults"]]
            },
            "pensieve": [c.to_dict() for c in pensieve],
            "discovered_studies": discovered_studies
        }
