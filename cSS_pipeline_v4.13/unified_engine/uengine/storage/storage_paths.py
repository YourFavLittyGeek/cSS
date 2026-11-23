"""uengine/storage/storage_paths.py - Canonical Storage Paths & Volume Identity Service.

Centralizes path containment validation, volume identity resolution, mount detection,
and canonical PERCIVAL storage directory layout.
"""

import os
import sys
import uuid
import shutil
import subprocess
from typing import Dict, Any, List, Optional, Tuple
from .models import VolumeInfo


DEFAULT_WORKSPACE = os.path.expanduser("~/Percival_project")
VAULT_DIRNAME = "PERCIVAL_VAULT"
VAULT_UUID_FILE = ".percival_vault_uuid"


class StoragePathsService:
    """Authoritative service for storage path resolution, containment, and volume identity."""

    def __init__(self, workspace_root: Optional[str] = None, configured_vault_mount: Optional[str] = None):
        self.workspace_root = os.path.abspath(workspace_root or DEFAULT_WORKSPACE)
        self.configured_vault = os.path.abspath(configured_vault_mount) if configured_vault_mount else None
        self._cached_vault_info: Optional[VolumeInfo] = None
        self._ensure_workspace_layout()

    def _ensure_workspace_layout(self) -> None:
        """Create standard local SSD workspace directory layout."""
        dirs = [
            os.path.join(self.workspace_root, "app_data"),
            os.path.join(self.workspace_root, "app_data", "transfers"),
            os.path.join(self.workspace_root, "app_data", "staging"),
            os.path.join(self.workspace_root, "app_data", "scratch"),
            os.path.join(self.workspace_root, "app_data", "quarantine"),
            os.path.join(self.workspace_root, "app_data", "logs"),
            os.path.join(self.workspace_root, "work"),
            os.path.join(self.workspace_root, "review"),
            os.path.join(self.workspace_root, "raw"),
            os.path.join(self.workspace_root, "data"),
            os.path.join(self.workspace_root, "results"),
            os.path.join(self.workspace_root, "runs"),
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)

    def get_internal_ssd_info(self) -> VolumeInfo:
        """Query macOS filesystem information for the internal SSD hosting the workspace."""
        st = os.statvfs(self.workspace_root)
        total = st.f_blocks * st.f_frsize
        available = st.f_bavail * st.f_frsize
        used = total - available

        return VolumeInfo(
            mount_point="/",
            volume_name="Macintosh HD",
            filesystem="apfs",
            device_node="/dev/disk3s1",
            volume_uuid="internal-mac-ssd",
            total_bytes=total,
            available_bytes=available,
            used_bytes=used,
            is_vault=False,
            is_internal=True,
            is_connected=True,
            read_only=False
        )

    def discover_external_volumes(self) -> List[VolumeInfo]:
        """Discover all mounted external volumes under /Volumes and check for PERCIVAL_VAULT."""
        volumes = []
        vol_root = "/Volumes"
        if not os.path.isdir(vol_root):
            return volumes

        for name in os.listdir(vol_root):
            if name.startswith("."):
                continue
            mp = os.path.join(vol_root, name)
            if not os.path.ismount(mp) and not os.path.isdir(mp):
                continue

            try:
                st = os.statvfs(mp)
                total = st.f_blocks * st.f_frsize
                available = st.f_bavail * st.f_frsize
                used = total - available

                # Check if internal volume link
                is_internal = (name == "Macintosh HD" or mp == "/")
                if is_internal:
                    continue

                # Query filesystem format via diskutil or stat
                fs_type = "unknown"
                dev_node = ""
                try:
                    r = subprocess.run(["diskutil", "info", "-plist", mp], capture_output=True)
                    if r.returncode == 0:
                        import plistlib
                        pl = plistlib.loads(r.stdout)
                        fs_type = pl.get("FilesystemType", "exfat").lower()
                        dev_node = pl.get("DeviceNode", "")
                except Exception:
                    pass

                # Check for Vault marker
                vault_dir = os.path.join(mp, VAULT_DIRNAME)
                is_vault = os.path.isdir(vault_dir)

                # Get or initialize Vault UUID
                vol_uuid = "unassigned"
                uuid_file = os.path.join(vault_dir, VAULT_UUID_FILE)
                if os.path.isfile(uuid_file):
                    try:
                        with open(uuid_file, "r") as f:
                            vol_uuid = f.read().strip()
                    except Exception:
                        pass

                info = VolumeInfo(
                    mount_point=mp,
                    volume_name=name,
                    filesystem=fs_type,
                    device_node=dev_node,
                    volume_uuid=vol_uuid,
                    total_bytes=total,
                    available_bytes=available,
                    used_bytes=used,
                    is_vault=is_vault,
                    is_internal=False,
                    is_connected=True,
                    read_only=not os.access(mp, os.W_OK)
                )
                volumes.append(info)
            except Exception:
                continue

        return volumes

    def get_vault_path(self) -> Optional[str]:
        """Resolve the active validated PERCIVAL_VAULT path."""
        # 1. Configured vault if valid
        if self.configured_vault and os.path.isdir(self.configured_vault):
            if os.path.basename(self.configured_vault) == VAULT_DIRNAME:
                return self.configured_vault
            cand = os.path.join(self.configured_vault, VAULT_DIRNAME)
            if os.path.isdir(cand):
                return cand

        # 2. Check mounted external volumes
        for v in self.discover_external_volumes():
            v_path = os.path.join(v.mount_point, VAULT_DIRNAME)
            if os.path.isdir(v_path):
                return v_path

        # 3. Direct check on /Volumes/Percival
        direct = "/Volumes/Percival/PERCIVAL_VAULT"
        if os.path.isdir(direct):
            return direct

        return None

    def get_vault_info(self) -> Optional[VolumeInfo]:
        """Query storage stats and volume identity of the active PERCIVAL Data Vault."""
        vp = self.get_vault_path()
        if not vp or not os.path.isdir(vp):
            return None

        st = os.statvfs(vp)
        total = st.f_blocks * st.f_frsize
        available = st.f_bavail * st.f_frsize
        used = total - available

        # Read UUID
        uuid_file = os.path.join(vp, VAULT_UUID_FILE)
        vol_uuid = "unknown"
        if os.path.isfile(uuid_file):
            try:
                with open(uuid_file, "r") as f:
                    vol_uuid = f.read().strip()
            except Exception:
                pass

        mount_pt = os.path.dirname(vp)
        return VolumeInfo(
            mount_point=mount_pt,
            volume_name=os.path.basename(mount_pt),
            filesystem="exfat",
            device_node="",
            volume_uuid=vol_uuid,
            total_bytes=total,
            available_bytes=available,
            used_bytes=used,
            is_vault=True,
            is_internal=False,
            is_connected=True,
            read_only=not os.access(vp, os.W_OK)
        )

    def is_contained_path(self, target_path: str, allowed_parents: Optional[List[str]] = None) -> bool:
        """Validate that target_path resides strictly within authorized directories."""
        real_target = os.path.realpath(os.path.abspath(target_path))
        parents = allowed_parents or [self.workspace_root]
        vp = self.get_vault_path()
        if vp:
            parents.append(os.path.realpath(vp))
            parents.append(os.path.realpath(os.path.dirname(vp)))

        for p in parents:
            real_p = os.path.realpath(os.path.abspath(p))
            if real_target == real_p or real_target.startswith(real_p + os.sep):
                return True
        return False
