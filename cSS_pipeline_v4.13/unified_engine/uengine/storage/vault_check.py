"""uengine/storage/vault_check.py - Phase 1e: read-only verification of a Vault location (never writes anything).

verify_vault(path) reports what the external archive can be used for:
  verdict "archive_ok"     exists, PERCIVAL_VAULT manifest present, on its own (external) volume, writable, and the
                           filesystem supports an exclusive commit -> stage FROM and archive TO
  verdict "not_external"   a valid Vault, but not on a separate external volume: usable as a source, not the archive
  verdict "read_only"      usable as a SOURCE only (stage / restore): exFAT (no exclusive commit), or mounted read-only
  verdict "not_a_vault"    reachable but no valid manifest/vault_manifest.json - nothing is archived there
  verdict "unavailable"    path / volume not present
plus the facts: mount point, filesystem type, read-only flag, internal-disk warning, free / total space.
"""
import json
import os
from typing import Any, Dict

from ..safety import volumes_root
from ..transfer.copier import NO_EXCLUSIVE_COMMIT_FS, fs_type, guarded_commit_fs


def _mount_point(path: str) -> str:
    p = os.path.realpath(path)
    while not os.path.ismount(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def verify_vault(path: str) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(path=path, verdict="unavailable", reasons=[], can_stage_from=False, can_archive_to=False)
    if not path or not os.path.isabs(path):
        out["reasons"].append("no absolute Vault path configured")
        return out
    if not os.path.isdir(path):
        out["reasons"].append("the Vault folder is not present (drive not connected?)")
        return out
    mnt = _mount_point(path)
    st = os.statvfs(path)
    ro = bool(st.f_flag & getattr(os, "ST_RDONLY", 1))
    fst = fs_type(path)
    internal = mnt in ("/", "/System/Volumes/Data") or not os.path.realpath(mnt).startswith(os.path.realpath(volumes_root()))
    out.update(mount_point=mnt, filesystem=fst, read_only=ro, internal_disk=internal,
               free_bytes=st.f_bavail * st.f_frsize, total_bytes=st.f_blocks * st.f_frsize,
               exclusive_commit=fst not in NO_EXCLUSIVE_COMMIT_FS if fst else None)
    man = os.path.join(path, "manifest", "vault_manifest.json")
    try:
        with open(man) as f:
            json.load(f)
        out["manifest"] = "valid"
    except FileNotFoundError:
        out["manifest"] = "missing"
    except (OSError, ValueError) as e:
        out["manifest"] = f"unreadable: {e}"
    if out["manifest"] != "valid":
        out["verdict"] = "not_a_vault"
        out["reasons"].append("manifest/vault_manifest.json is missing or invalid - this folder is not treated as a Vault")
        return out
    out["can_stage_from"] = True
    if internal:
        out["reasons"].append("the Vault is not on a separate external volume (it is not the permanent archive drive)")
    guarded = guarded_commit_fs(fst)
    out["guarded_commit"] = guarded
    if guarded:
        out["reasons"].append(f"{fst}: files are archived with Percival's guarded commit (locked check-then-rename, never overwrites)")
    elif fst in NO_EXCLUSIVE_COMMIT_FS:
        out["reasons"].append(f"{fst} cannot guarantee that an archived file is never overwritten; archiving to it is refused")
    if ro:
        out["reasons"].append("the volume is mounted read-only")
    if internal:
        out["verdict"] = "not_external"
    elif (fst in NO_EXCLUSIVE_COMMIT_FS and not guarded) or ro or fst == "":
        out["verdict"] = "read_only"
        if fst == "":
            out["reasons"].append("the filesystem type could not be determined")
    else:
        out["verdict"] = "archive_ok"
        out["can_archive_to"] = True
    return out
