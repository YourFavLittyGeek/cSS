"""Authoritative validators for PERCIVAL setup components.

Mission ID: PERCIVAL-SETUP-REDESIGN-2026
"""

import os
import sys
import re
import json
import shutil
import sqlite3
import subprocess
from typing import Dict, Any, List, Optional

REQUIRED_PYTHON_PKGS = [
    "numpy", "scipy", "nibabel", "pandas", "skimage",
    "matplotlib", "pydicom", "openpyxl", "cryptography"
]

FS_REQUIRED_TOOLS = ["mri_synthseg", "mri_synthstrip", "mri_convert", "mri_vol2vol"]
FS_ALL_TOOLS = ["mri_synthseg", "mri_synthstrip", "mri_convert", "mri_vol2vol", "mri_coreg", "recon-all", "bbregister", "freeview"]


def validate_python(executable_path: Optional[str] = None) -> Dict[str, Any]:
    """Validate a Python environment for version and required scientific packages."""
    exe = os.path.abspath(os.path.expanduser(executable_path or sys.executable))
    if not os.path.isfile(exe) or not os.access(exe, os.X_OK):
        return {
            "ok": False,
            "executable": exe,
            "error": f"Python executable not found or not executable: {exe}",
            "version": "unknown",
            "missing_packages": REQUIRED_PYTHON_PKGS,
            "installed_packages": {}
        }

    script = f"""
import sys, json, platform
res = {{
    "version": platform.python_version(),
    "version_info": list(sys.version_info[:3]),
    "executable": sys.executable,
    "packages": {{}},
    "missing": []
}}
for pkg in {REQUIRED_PYTHON_PKGS!r}:
    try:
        mod = __import__(pkg)
        res["packages"][pkg] = getattr(mod, "__version__", "installed")
    except Exception:
        res["missing"].append(pkg)
print(json.dumps(res))
"""
    try:
        r = subprocess.run([exe, "-c", script], capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return {
                "ok": False,
                "executable": exe,
                "error": f"Python test process exited with code {r.returncode}: {r.stderr.strip()}",
                "version": "unknown",
                "missing_packages": REQUIRED_PYTHON_PKGS,
                "installed_packages": {}
            }
        data = json.loads(r.stdout.strip())
        is_ver_ok = data["version_info"][0] == 3 and data["version_info"][1] >= 10
        missing = data.get("missing", [])
        ok = is_ver_ok and len(missing) == 0

        err_msg = ""
        if not is_ver_ok:
            err_msg = f"Python {data['version']} is too old (Python 3.10+ required)."
        elif missing:
            err_msg = f"Missing required packages: {', '.join(missing)}"

        return {
            "ok": ok,
            "executable": exe,
            "version": data["version"],
            "version_info": data["version_info"],
            "missing_packages": missing,
            "installed_packages": data.get("packages", {}),
            "error": err_msg
        }
    except Exception as e:
        return {
            "ok": False,
            "executable": exe,
            "error": f"Failed to test Python environment: {e}",
            "version": "unknown",
            "missing_packages": REQUIRED_PYTHON_PKGS,
            "installed_packages": {}
        }


def validate_pipeline(pipeline_dir: str) -> Dict[str, Any]:
    """Validate a PERCIVAL pipeline directory for scripts, version metadata, and entry points."""
    pdir = os.path.abspath(os.path.expanduser(pipeline_dir or ""))
    if not os.path.isdir(pdir):
        return {
            "ok": False,
            "path": pdir,
            "error": f"Pipeline directory does not exist: {pdir}",
            "version": "unknown",
            "build": "unknown",
            "entry_point": None
        }

    # Pipeline scripts may reside in pdir/scripts or directly in pdir
    scripts_dir = os.path.join(pdir, "scripts") if os.path.isdir(os.path.join(pdir, "scripts")) else pdir
    run_css = os.path.join(scripts_dir, "run_css.sh")
    detect_css = os.path.join(scripts_dir, "detect_css.py")
    score_css = os.path.join(scripts_dir, "score_css.py")

    missing = []
    if not os.path.isfile(run_css): missing.append("run_css.sh")
    if not os.path.isfile(detect_css): missing.append("detect_css.py")
    if not os.path.isfile(score_css): missing.append("score_css.py")

    if missing:
        return {
            "ok": False,
            "path": pdir,
            "error": f"Pipeline entry points missing from {scripts_dir}: {', '.join(missing)}",
            "version": "unknown",
            "build": "unknown",
            "entry_point": None
        }

    # Parse version and build
    version = "v5.26"
    vf = os.path.join(scripts_dir, "VERSION")
    if os.path.isfile(vf):
        try:
            with open(vf, "r") as f:
                version = f.read().strip()[:100]
        except Exception:
            pass

    build = "production"
    bf = os.path.join(scripts_dir, "BUILD")
    if os.path.isfile(bf):
        try:
            with open(bf, "r") as f:
                build = f.read().strip()[:100]
        except Exception:
            pass

    # Count executable scripts
    all_scripts = [f for f in os.listdir(scripts_dir) if f.endswith((".py", ".sh"))]

    return {
        "ok": True,
        "path": pdir,
        "scripts_dir": scripts_dir,
        "entry_point": run_css,
        "version": version,
        "build": build,
        "script_count": len(all_scripts),
        "error": ""
    }


def validate_freesurfer(fs_dir: str) -> Dict[str, Any]:
    """Validate a FreeSurfer installation directory and tool suite."""
    d = os.path.abspath(os.path.expanduser(fs_dir or ""))
    if not d or not os.path.isdir(d):
        return {"ok": False, "home": d, "error": f"FreeSurfer directory not found: {d}", "tools": {}}

    tools_status = {t: os.path.isfile(os.path.join(d, "bin", t)) for t in FS_ALL_TOOLS}
    missing_required = [t for t in FS_REQUIRED_TOOLS if not tools_status.get(t, False)]

    if missing_required:
        return {
            "ok": False,
            "home": d,
            "tools": tools_status,
            "error": f"Incomplete FreeSurfer installation: missing bin/{', bin/'.join(missing_required)}"
        }

    # Read build-stamp
    ver = "unknown"
    bs = os.path.join(d, "build-stamp.txt")
    if os.path.isfile(bs):
        try:
            with open(bs, "r", errors="replace") as f:
                ver = f.read().strip()[:160]
        except Exception:
            pass

    m = re.search(r"(\d+)\.(\d+)\.(\d+)", ver)
    major = int(m.group(1)) if m else None
    warning = ""
    if not major or major < 7:
        warning = f"FreeSurfer {ver}: version 7 or newer is recommended."

    return {
        "ok": True,
        "home": d,
        "version": ver,
        "major": major,
        "tools": tools_status,
        "warning": warning,
        "error": ""
    }


def validate_license(lic_path: str) -> Dict[str, Any]:
    """Validate structure of FreeSurfer license without returning or logging secret keys."""
    p = os.path.abspath(os.path.expanduser(lic_path or ""))
    if not p or not os.path.isfile(p):
        return {"ok": False, "path": p, "error": f"Licence file not found: {p}"}
    if not os.access(p, os.R_OK):
        return {"ok": False, "path": p, "error": f"Permission denied reading licence file: {p}"}
    if os.path.getsize(p) > 4096:
        return {"ok": False, "path": p, "error": "File exceeds maximum valid size for FreeSurfer licence (>4KB)"}

    try:
        with open(p, "r", errors="replace") as f:
            lines = [x.strip() for x in f.read().splitlines() if x.strip()]
    except Exception as e:
        return {"ok": False, "path": p, "error": f"Unreadable licence file: {e}"}

    ok = len(lines) >= 3 and "@" in lines[0] and all(len(x) >= 4 for x in lines[1:4])
    return {
        "ok": ok,
        "path": p,
        "n_lines": len(lines),
        "error": "" if ok else "File does not match expected FreeSurfer licence structure (email + key lines)"
    }


def validate_mri_tool(tool_name: str, exec_path: Optional[str] = None) -> Dict[str, Any]:
    """Validate executable tool presence and execute non-destructive version check."""
    exe = exec_path or shutil.which(tool_name)
    if not exe:
        # Check standard Homebrew and Conda locations
        for cand in [
            f"/opt/homebrew/bin/{tool_name}",
            f"/usr/local/bin/{tool_name}",
            os.path.expanduser(f"~/miniforge3/envs/css/bin/{tool_name}"),
            os.path.expanduser(f"~/miniforge3/bin/{tool_name}")
        ]:
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                exe = cand
                break

    if not exe or not os.path.isfile(exe):
        return {
            "ok": False,
            "tool": tool_name,
            "path": None,
            "version": "not installed",
            "error": f"Tool '{tool_name}' not found on system PATH or standard directories"
        }

    version = "installed"
    try:
        flag = "-v" if tool_name == "dcm2niix" else "--version"
        r = subprocess.run([exe, flag], capture_output=True, text=True, timeout=5)
        out = (r.stdout + r.stderr).strip().splitlines()
        if out:
            version = out[0][:100]
    except Exception:
        pass

    return {
        "ok": True,
        "tool": tool_name,
        "path": exe,
        "version": version,
        "error": ""
    }


def validate_workspace(path: str) -> Dict[str, Any]:
    """Validate internal SSD workspace directory writeability and available headroom."""
    p = os.path.abspath(os.path.expanduser(path or "~/Percival_project"))
    try:
        os.makedirs(p, exist_ok=True)
        # Test writeability
        test_file = os.path.join(p, ".percival_write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)

        usage = shutil.disk_usage(p)
        free_gb = round(usage.free / (1024**3), 1)
        total_gb = round(usage.total / (1024**3), 1)

        warning = ""
        if free_gb < 15.0:
            warning = f"Low disk space on workspace drive: {free_gb} GB free (at least 15 GB recommended)."

        return {
            "ok": True,
            "path": p,
            "free_gb": free_gb,
            "total_gb": total_gb,
            "writable": True,
            "warning": warning,
            "error": ""
        }
    except Exception as e:
        return {
            "ok": False,
            "path": p,
            "free_gb": 0.0,
            "total_gb": 0.0,
            "writable": False,
            "warning": "",
            "error": f"Workspace directory not writable: {e}"
        }


def validate_vault(path: str) -> Dict[str, Any]:
    """Validate external Data Vault path, UUID identity, and existing archives."""
    p = os.path.abspath(os.path.expanduser(path or ""))
    if not os.path.isdir(p):
        return {
            "ok": False,
            "path": p,
            "connected": False,
            "error": f"Data Vault path does not exist or is not mounted: {p}"
        }

    try:
        # Check write access
        writable = os.access(p, os.W_OK)
        usage = shutil.disk_usage(p)
        free_gb = round(usage.free / (1024**3), 1)
        total_gb = round(usage.total / (1024**3), 1)

        # Detect existing archives
        studies_dir = os.path.join(p, "studies")
        pensieve_dir = os.path.join(p, "PENSIEVE")
        existing_studies = len(os.listdir(studies_dir)) if os.path.isdir(studies_dir) else 0
        has_pensieve = os.path.isdir(pensieve_dir)

        # Check UUID
        uuid_file = os.path.join(p, ".percival_vault_uuid")
        vault_uuid = "unassigned"
        if os.path.isfile(uuid_file):
            try:
                with open(uuid_file, "r") as uf:
                    vault_uuid = uf.read().strip()
            except Exception:
                pass

        return {
            "ok": True,
            "path": p,
            "connected": True,
            "writable": writable,
            "free_gb": free_gb,
            "total_gb": total_gb,
            "vault_uuid": vault_uuid,
            "existing_studies_count": existing_studies,
            "has_pensieve_backup": has_pensieve,
            "error": "" if writable else "Vault volume is mounted read-only."
        }
    except Exception as e:
        return {
            "ok": False,
            "path": p,
            "connected": False,
            "error": f"Failed to access Vault volume: {e}"
        }


def validate_pensieve(db_path: str) -> Dict[str, Any]:
    """Validate SQLite Pensieve database schema and integrity."""
    p = os.path.abspath(os.path.expanduser(db_path or ""))
    if not os.path.isfile(p):
        return {"ok": False, "path": p, "error": f"Database file not found: {p}"}

    try:
        con = sqlite3.connect(p, timeout=5.0)
        cur = con.cursor()
        cur.execute("PRAGMA integrity_check;")
        res = cur.fetchone()
        integrity_ok = res and res[0] == "ok"

        # Query table list
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cur.fetchall()]

        # Query stats
        studies_cnt = 0
        calls_cnt = 0
        if "patients" in tables:
            try:
                cur.execute("SELECT COUNT(*) FROM patients;")
                studies_cnt = cur.fetchone()[0]
            except Exception: pass
        if "adjudication_calls" in tables:
            try:
                cur.execute("SELECT COUNT(*) FROM adjudication_calls;")
                calls_cnt = cur.fetchone()[0]
            except Exception: pass

        con.close()
        return {
            "ok": integrity_ok,
            "path": p,
            "size_bytes": os.path.getsize(p),
            "tables": tables,
            "table_count": len(tables),
            "studies_count": studies_cnt,
            "calls_count": calls_cnt,
            "error": "" if integrity_ok else f"Integrity check failed: {res[0] if res else 'unknown'}"
        }
    except Exception as e:
        return {"ok": False, "path": p, "error": f"SQLite error: {e}"}
