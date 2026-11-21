"""setup_gui.py - first-run installation / configuration wizard (v5.17). Research software; everything is checked on this computer.

checks()          the readiness checklist: REQUIRED (OS, Python packages, data / model folders writable, pipeline installed, FreeSurfer folder
                  + version + tools, FreeSurfer licence, DICOM tools) and OPTIONAL (own app window, acceleration, Image ML model, memory, disk)
validate_fs(dir)  is a folder a FreeSurfer installation? (bin/ tools, build-stamp version) - never assumes a fixed location
validate_license  is a file a usable FreeSurfer licence? It is read HERE ONLY to check its structure (line count, an e-mail-like first line,
                  key lines); its content is never returned, logged, copied or transmitted
test_fs(...)      runs a FreeSurfer tool locally (mri_convert --version) with the chosen folder and licence
report()          final readiness report (app_data/setup_report.json; no licence content); setup_done marks the wizard as completed"""
import datetime, glob, importlib, json, os, platform, re, shutil, subprocess, sys

REQUIRED_PKGS = ["numpy", "scipy", "nibabel", "pandas", "skimage", "matplotlib", "pydicom", "openpyxl", "cryptography"]
FS_TOOLS = ["mri_synthseg", "mri_synthstrip", "mri_convert", "mri_vol2vol", "mri_coreg", "recon-all", "bbregister", "freeview"]
FS_REQUIRED_TOOLS = ["mri_synthseg", "mri_synthstrip", "mri_convert", "mri_vol2vol"]


def _item(id_, label, required, ok, detail, fix="", group=""):
    return dict(id=id_, label=label, required=required, ok=bool(ok), detail=detail, fix=fix, group=group)


def validate_fs(d):
    d = os.path.expanduser(str(d or "")).rstrip("/")
    if not d: return dict(ok=False, error="no folder chosen")
    if not os.path.isdir(d): return dict(ok=False, error="not a folder")
    tools = {t: os.path.exists(os.path.join(d, "bin", t)) for t in FS_TOOLS}
    ver = ""
    bs = os.path.join(d, "build-stamp.txt")
    if os.path.exists(bs):
        with open(bs, errors="replace") as f: ver = f.read().strip()[:160]
    miss = [t for t in FS_REQUIRED_TOOLS if not tools[t]]
    if miss: return dict(ok=False, home=d, version=ver, tools=tools, error=f"this folder is not a usable FreeSurfer installation: bin/{', bin/'.join(miss)} missing")
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", ver)
    major = int(m.group(1)) if m else None
    warn = "" if major and major >= 7 else ("FreeSurfer version not recognised (build-stamp.txt)" if not m else f"FreeSurfer {m.group(0)}: version 7 or newer is recommended")
    return dict(ok=True, home=d, version=ver, major=major, tools=tools, warning=warn)


def validate_license(p):
    """structure check only - the content is never returned"""
    p = os.path.expanduser(str(p or ""))
    if not p: return dict(ok=False, error="no licence file chosen")
    if not os.path.isfile(p): return dict(ok=False, error="not a file")
    if not os.access(p, os.R_OK): return dict(ok=False, error="this user cannot read the file (check its permissions)")
    if os.path.getsize(p) > 4096: return dict(ok=False, error="too large for a FreeSurfer licence file")
    try:
        with open(p, errors="replace") as f: lines = [x.strip() for x in f.read().splitlines() if x.strip()]
    except Exception as e: return dict(ok=False, error=f"unreadable: {type(e).__name__}")
    ok = len(lines) >= 3 and "@" in lines[0] and all(len(x) >= 4 for x in lines[1:4])
    return dict(ok=ok, path=p, n_lines=len(lines), error="" if ok else "this file does not look like a FreeSurfer licence (expected: e-mail line + key lines)")


def test_fs(home, lic, run=subprocess.run):
    v = validate_fs(home); l = validate_license(lic)
    if not v["ok"]: return dict(ok=False, error=v["error"])
    if not l["ok"]: return dict(ok=False, error=l["error"])
    env = dict(os.environ, FREESURFER_HOME=v["home"], FS_LICENSE=l["path"], PATH=f"{v['home']}/bin:" + os.environ.get("PATH", ""))
    try:
        r = run([os.path.join(v["home"], "bin", "mri_convert"), "--version"], capture_output=True, text=True, timeout=60, env=env)
        out = (r.stdout + r.stderr).strip().splitlines()
        return dict(ok=r.returncode == 0, version_line=(out[0][:160] if out else ""), error="" if r.returncode == 0 else f"mri_convert exit {r.returncode}")
    except Exception as e: return dict(ok=False, error=f"FreeSurfer could not run: {type(e).__name__}: {e}"[:300])


def _writable(d):
    try:
        os.makedirs(d, exist_ok=True); t = os.path.join(d, ".percival_write_test"); open(t, "w").close(); os.remove(t); return True
    except Exception: return False


def checks(B, AD, SET, fs_env, find_license, which, engine_root, models_ok=None):
    out = []
    out.append(_item("os", "Operating system", True, sys.platform == "darwin", f"{platform.system()} {platform.mac_ver()[0] or platform.release()} · {platform.machine()}", group="System"))
    out.append(_item("python", "Python environment", True, sys.version_info[:2] >= (3, 10), f"python {platform.python_version()} ({sys.executable})", group="System"))
    miss = []
    for m in REQUIRED_PKGS:
        try: importlib.import_module(m)
        except Exception: miss.append(m)
    out.append(_item("packages", "Required Python packages", True, not miss, "all present" if not miss else "missing: " + ", ".join(miss), fix="" if not miss else "conda", group="System"))
    out.append(_item("appdata", "Application data folder", True, _writable(AD), AD, group="Folders"))
    md = os.path.join(engine_root, "models")
    out.append(_item("models_dir", "Model storage folder", True, os.path.isdir(md) and os.access(md, os.R_OK), md, group="Folders"))
    out.append(_item("project", "Project folder writable", True, _writable(os.path.join(B, "review")), B, group="Folders"))
    rc = os.path.join(B, "scripts", "run_css.sh")    # the app runs the pipeline from <project>/scripts (css_app.SC); no fallback to the repository copy
    out.append(_item("pipeline", "Pipeline installed", True, os.path.exists(rc), rc if os.path.exists(rc) else f"{rc} not found - processing cannot run in this project",
                     fix="" if os.path.exists(rc) else "pipeline", group="Folders"))
    env = fs_env(); fh = SET.get("freesurfer_home") or env.get("FREESURFER_HOME", "")
    v = validate_fs(fh) if fh else dict(ok=False, error="no FreeSurfer folder set or found")
    out.append(_item("freesurfer", "FreeSurfer installation", True, v["ok"], (f"{v.get('home')} · {v.get('version') or 'version unknown'}" + (f" · {v['warning']}" if v.get("warning") else "")) if v["ok"] else v["error"],
                     fix="fs_home", group="FreeSurfer"))
    lic = find_license(fh, env) or SET.get("fs_license", "")
    lv = validate_license(lic) if lic else dict(ok=False, error="licence file not found")
    out.append(_item("license", "FreeSurfer licence", True, lv["ok"], f"{lv.get('path')} (structure valid; contents not shown)" if lv["ok"] else lv["error"], fix="fs_license", group="FreeSurfer"))
    for t in ("dcm2niix", "dcmdjpeg"):
        w = which(t, env); out.append(_item(t, f"MRI tool: {t}", t == "dcm2niix", bool(w), w or "not found", fix="dcm2niix" if t == "dcm2niix" and not w else "", group="MRI processing"))
    try:
        import webview  # noqa
        out.append(_item("window", "Own app window (pywebview)", False, True, "installed", group="Optional"))
    except Exception: out.append(_item("window", "Own app window (pywebview)", False, False, "not installed - the app opens in the browser", fix="pywebview", group="Optional"))
    acc = "Apple Silicon (" + platform.machine() + "): CPU processing; no GPU needed (no deep-learning model is used)" if platform.machine() == "arm64" else "CPU processing; no GPU needed"
    out.append(_item("accel", "Acceleration", False, True, acc, group="Optional"))
    try: mo = models_ok() if models_ok else None
    except Exception: mo = None
    out.append(_item("imageml", "Image ML model (local)", False, bool(mo), "healthy synthetic demonstration model (applies to synthetic studies only)" if mo else "no healthy image model", group="Optional"))
    du = shutil.disk_usage(B); out.append(_item("disk", "Disk space", False, du.free / 1e9 > 15, f"{du.free / 1e9:.0f} GB free", group="Optional"))
    return out


def report(items, AD, done=False):
    req = [i for i in items if i["required"]]; rep = dict(created=datetime.datetime.now().isoformat(timespec="seconds"), ready=all(i["ok"] for i in req),
                                                          required_ok=sum(i["ok"] for i in req), required_total=len(req),
                                                          optional_ok=sum(i["ok"] for i in items if not i["required"]), optional_total=sum(1 for i in items if not i["required"]),
                                                          items=[{k: i[k] for k in ("id", "label", "required", "ok", "detail", "group")} for i in items])
    with open(os.path.join(AD, "setup_report.json"), "w") as f: json.dump(rep, f, indent=1)
    if done:
        with open(os.path.join(AD, "setup_done.json"), "w") as f: json.dump(dict(done=rep["created"], ready=rep["ready"]), f)
    return rep


def first_run(AD): return not os.path.exists(os.path.join(AD, "setup_done.json"))
