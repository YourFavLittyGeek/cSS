"""study_library.py - v5.18 Study library: a COPY of each imported examination, organised by patient and examination. Local only.

    Standard mode:   <library>/<MRN>/<accession number>/{T1,SWI,PHASE,FLAIR,other}/...
    Incognito mode:  <library>/<de-identified study code>/{T1,SWI,...}/...        (no patient grouping in Incognito)

Rules
- The original folders are never renamed, moved or changed: the library receives a copy (an APFS clone when the library is on the same
  disk, so it takes no extra space), verified file by file (sha256) before it is accepted.
- Accession numbers are never invented: a Standard examination without one has no library place (refused, reported).
- An existing library folder is never overwritten: the same examination (same image fingerprint) is "already in the library";
  anything else is a conflict for the user to resolve.
- Files get neutral names inside the folder (SWI_00001.dcm, T1.nii.gz, ...): original file names can hold a patient name.
- The library location must be a verified local folder (no cloud-synced folder, not Desktop / Documents, not a protected project).
- The library path of a Standard examination holds MRN + accession, so it is stored only in the encrypted vault; the app logs and
  exports never contain it.
"""
import hashlib, json, os, re, secrets, shutil, subprocess, threading, time

TYPES = ("SWI", "T1", "PHASE", "FLAIR")
SEG = re.compile(r"[^A-Za-z0-9._-]+")
LOCK = threading.Lock()
JOBS = {}                                   # job id -> dict(state, done, total, items=[dict(code, state, msg)])


def segment(x):
    """one safe folder name from an identifier (letters, digits . _ -); '' when nothing usable is left"""
    s = SEG.sub("_", str(x or "").strip()).strip("._")
    return "" if s in ("", ".", "..") else s[:64]


def place(mode, mrn="", accession="", study_code=""):
    """-> (relative folder, '') or ('', reason). Never invents an identifier."""
    if mode == "standard":
        a, m = segment(accession), segment(mrn)
        if not a: return "", "accession number missing - the examination cannot be placed in the library (it is never generated)"
        if not m: return "", "MRN missing - the examination cannot be placed in the library"
        return os.path.join(m, a), ""
    s = segment(study_code)
    if not s: return "", "de-identified study code missing"
    return s, ""


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""): h.update(b)
    return h.hexdigest()


def _cp(a, b):
    if subprocess.run(["cp", "-c", a, b], capture_output=True).returncode != 0: shutil.copy2(a, b)


def _files_of(src):
    if os.path.isfile(src): return [src]
    return [os.path.join(src, f) for f in sorted(os.listdir(src)) if not f.startswith(".") and os.path.isfile(os.path.join(src, f))]


def layout(chosen, all_series=(), whole_exam=False, mode="incognito"):
    """-> [(source file, relative destination)] with neutral names. chosen: {TYPE: path}; all_series: scan dicts of the examination"""
    out = []
    def add(src, folder, stem):
        if os.path.isfile(src) and src.endswith((".nii", ".nii.gz")):
            ext = ".nii.gz" if src.endswith(".nii.gz") else ".nii"
            out.append((src, os.path.join(folder, stem + ext)))
            js = re.sub(r"\.nii(\.gz)?$", ".json", src)
            if os.path.exists(js): out.append((js, os.path.join(folder, stem + ".json")))
        else:
            for i, f in enumerate(_files_of(src), 1): out.append((f, os.path.join(folder, f"{stem}_{i:05d}.dcm")))
    used = set()
    for t in TYPES:
        if chosen.get(t): add(chosen[t], t, t); used.add(chosen[t])
    if whole_exam:
        n = 0
        for s in all_series:
            if not s.get("ok") or s["path"] in used: continue
            n += 1; d = segment(s.get("description", "")) if mode == "standard" else ""
            add(s["path"], os.path.join("other", f"series_{n:02d}" + (f"_{d[:40]}" if d else "")), f"series_{n:02d}")
    return out


def copy_exam(library, rel, files, meta, fingerprint=""):
    """copy + verify into <library>/<rel>. -> dict(state: copied | already | conflict | failed, msg, n, bytes). Never overwrites."""
    dest = os.path.join(library, rel)
    if os.path.exists(dest):
        mf = os.path.join(dest, "percival_library.json")
        try:
            old = json.load(open(mf))
            if fingerprint and old.get("fingerprint") == fingerprint: return dict(state="already", msg="already in the library (same images)", n=old.get("n_files", 0))
        except Exception: pass
        return dict(state="conflict", msg="a different examination already uses this library folder - nothing was overwritten; check the identifiers")
    tmp = os.path.join(os.path.dirname(dest), f".partial_{secrets.token_hex(4)}_{os.path.basename(dest)}")
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True); os.makedirs(tmp)
        rec = []; nbytes = 0
        for src, r in files:
            t = os.path.join(tmp, r); os.makedirs(os.path.dirname(t), exist_ok=True); _cp(src, t)
            a, b = sha256(src), sha256(t)
            if a != b: raise IOError(f"verification failed for {r}")
            rec.append(dict(file=r, sha256=b, bytes=os.path.getsize(t))); nbytes += os.path.getsize(t)
        json.dump(dict(meta, fingerprint=fingerprint, copied=time.strftime("%Y-%m-%d %H:%M:%S"), n_files=len(rec), bytes=nbytes, files=rec,
                       note="copy of the original examination (originals unchanged); verified with sha256"), open(os.path.join(tmp, "percival_library.json"), "w"), indent=1)
        os.rename(tmp, dest)
        return dict(state="copied", msg=f"{len(rec)} files copied and verified", n=len(rec), bytes=nbytes)
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return dict(state="failed", msg=f"{type(e).__name__}: {str(e)[:160]}")


def start_job(library, items, on_item=None):
    """background copy of several examinations. items: dict(code, rel, files, meta, fingerprint). -> job id"""
    jid = secrets.token_urlsafe(8)
    with LOCK: JOBS[jid] = dict(state="running", done=0, total=len(items), started=time.time(), items=[dict(code=i["code"], state="waiting", msg="") for i in items])
    def run():
        for k, it in enumerate(items):
            with LOCK: JOBS[jid]["items"][k]["state"] = "copying"
            r = copy_exam(library, it["rel"], it["files"], it["meta"], it.get("fingerprint", ""))
            with LOCK: JOBS[jid]["items"][k].update(state=r["state"], msg=r["msg"]); JOBS[jid]["done"] = k + 1
            if on_item:
                try: on_item(it, r)
                except Exception: pass
        with LOCK: JOBS[jid]["state"] = "finished"; JOBS[jid]["finished"] = time.time()
    threading.Thread(target=run, daemon=True).start()
    return jid


def job(jid):
    with LOCK:
        j = JOBS.get(jid)
        return json.loads(json.dumps(j)) if j else None
