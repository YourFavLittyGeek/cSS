"""Reconnect the Pensieve drive when it is plugged in but not mounted (2026-11-25).

The app's Eject uses `diskutil unmount`: the drive stays attached, and macOS never mounts an attached-but-unmounted
volume again by itself (only unplugging + plugging back in does). So after an Eject - or a macOS unmount after sleep -
the app kept saying "not connected" even after it was reopened.

find_unmounted(name)  -> device identifier (e.g. disk4s2) of an EXTERNAL partition whose volume name is `name` and that
                         has no mount point; None otherwise (read-only: `diskutil list -plist external`)
mount(dev)            -> (ok, message) via `diskutil mount <dev>` (mounting never changes the drive's content)
volume_name(vault)    -> the volume name of a configured Vault path under the volumes root (/Volumes/<name>/...)
The command runner is injectable (tests); nothing here runs diskutil under test isolation unless a runner is passed."""
import os
import plistlib
import subprocess
import time

_CACHE = {"t": 0.0, "name": "", "dev": None}


def _real_run(cmd):
    if os.environ.get("PERCIVAL_TEST_ISOLATION") == "1":
        raise RuntimeError("diskutil is never run under test isolation")
    return subprocess.run(cmd, capture_output=True, timeout=30)


def volume_name(vault_path, volumes_root=None):
    root = os.path.abspath(volumes_root or os.environ.get("PERCIVAL_VOLUMES_ROOT") or "/Volumes")
    p = os.path.abspath(vault_path or "")
    if not p.startswith(root + os.sep): return ""
    return p[len(root) + 1:].split(os.sep)[0]


def find_unmounted(name, run=None, cache_s=0.0):
    """device id of the attached, unmounted external partition called `name` (None if mounted, absent or unknown)"""
    if not name: return None
    now = time.time()
    if cache_s and _CACHE["name"] == name and now - _CACHE["t"] < cache_s: return _CACHE["dev"]
    run = run or _real_run
    dev = None
    try:
        r = run(["diskutil", "list", "-plist", "external"])
        if r.returncode == 0:
            d = plistlib.loads(r.stdout if isinstance(r.stdout, bytes) else r.stdout.encode())
            for disk in d.get("AllDisksAndPartitions", []):
                for part in disk.get("Partitions", []) + ([disk] if disk.get("VolumeName") else []):
                    if part.get("VolumeName") == name and not part.get("MountPoint"):
                        dev = part.get("DeviceIdentifier"); break
                if dev: break
    except Exception:
        dev = None
    _CACHE.update(t=now, name=name, dev=dev)
    return dev


def mount(dev, run=None):
    if not dev or not dev.replace("disk", "").replace("s", "").isdigit():
        return False, f"not a disk identifier: {dev!r}"
    run = run or _real_run
    try:
        r = run(["diskutil", "mount", dev])
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    out = ((r.stdout or b"") + (r.stderr or b"")).decode(errors="replace").strip() if isinstance(r.stdout, bytes) else f"{r.stdout}{r.stderr}".strip()
    _CACHE["t"] = 0.0
    return r.returncode == 0, out or ("mounted" if r.returncode == 0 else "diskutil mount failed")
