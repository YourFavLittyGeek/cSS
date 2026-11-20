"""Previous Processing Manager (experimental/unified-gui).

Finds earlier processing of a study (made by this app, an older app or the terminal workflow), checks per
stage whether it belongs to the exact MRI now in data/, and keeps every run separately with a manifest.
Rules:
  * nothing is deleted or overwritten: before a stage is re-run, the current outputs are archived (copied)
    under runs/<ID>/<run_id>/files/. A FreeSurfer directory is never copied over or removed; it is only
    renamed aside (subjects/<ID> -> subjects/<ID>__run_<run_id>) when the user explicitly asks for a new recon;
  * reader files (review/<ID>_calls*.csv, reviewers.json, final/score files written by the reviewer) are
    never touched;
  * FreeSurfer is never re-run when a complete, compatible recon exists unless the user confirms;
  * dependencies: anatomy -> registration -> align -> detect -> unified. Re-running a stage re-runs every
    later stage; a stage is reusable only when every earlier stage is;
  * a failed run restores the previous outputs of the stages it touched, so the active result is unchanged.

Categories (user's specification): compatible, compatible_with_limitations, incomplete, incompatible,
corrupted, unknown; plus missing (no output) and upstream (an earlier stage must be re-run first).
"""
import hashlib, json, os, shutil, time, glob

STAGES = ["anatomy", "registration", "align", "detect", "unified"]
COMPAT, LIMITED, INCOMPLETE, INCOMPAT, CORRUPT, UNKNOWN = "compatible", "compatible_with_limitations", "incomplete", "incompatible", "corrupted", "unknown"
MISSING, UPSTREAM, NA = "missing", "upstream_rerun", "not_applicable"
REUSABLE = (COMPAT, LIMITED, UNKNOWN, NA)            # UNKNOWN only after the user confirms (adopt) - see plan()
LABEL = {COMPAT: "compatible", LIMITED: "compatible with limitations", INCOMPLETE: "incomplete", INCOMPAT: "incompatible",
         CORRUPT: "corrupted", UNKNOWN: "unknown", MISSING: "missing", NA: "not applicable (SWI-only route)", UPSTREAM: "needs re-run (earlier stage changes)"}

def _sha(p, cache={}):
    st = os.stat(p); k = (p, st.st_size, st.st_mtime)
    if k not in cache:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
        cache[k] = h.hexdigest()
    return cache[k]

def _jl(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d

def _js(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True); t = p + ".tmp"
    with open(t, "w") as f: json.dump(d, f, indent=1)
    os.replace(t, p)

def _readable(p):
    """header-level integrity: NIfTI / MGZ header loads, JSON parses, CSV has a header line. True / False / None (not checkable)"""
    try:
        if p.endswith((".nii", ".nii.gz", ".mgz", ".mgh")):
            import nibabel as nib
            img = nib.load(p); img.header.get_data_shape()
            if p.endswith((".gz", ".mgz")):                    # gzip: read the stream end to catch truncation
                import gzip
                with gzip.open(p, "rb") as f:
                    while f.read(1 << 22): pass
            return True
        if p.endswith(".json"): json.load(open(p)); return True
        if p.endswith(".csv"): return bool(open(p, errors="replace").readline().strip())
        if p.endswith(".lta"): return "1 4 4" in open(p, errors="replace").read() or "LINEAR_" in open(p, errors="replace").read()
    except Exception: return False
    return None

def image_identity(p):
    out = dict(sha256=_sha(p))
    try:
        import nibabel as nib
        img = nib.load(p); h = img.header
        out.update(dims=[int(x) for x in h.get_data_shape()[:3]], voxel_mm=[round(float(x), 3) for x in h.get_zooms()[:3]],
                   orientation="".join(nib.aff2axcodes(img.affine)), qform_code=int(h["qform_code"]) if "qform_code" in h else None,
                   sform_code=int(h["sform_code"]) if "sform_code" in h else None)
    except Exception as e: out["header_error"] = str(e)[:120]
    return out

class Study:
    def __init__(self, base, sid, subjects_dir=None):
        self.B, self.S = base, sid
        self.SD = subjects_dir or os.environ.get("CSS_SUBJECTS_DIR") or os.path.join(base, "subjects")
        self.R = os.path.join(base, "runs", sid)

    # ---- files per stage (reader files deliberately absent) ----
    def files(self, stage):
        B, S = self.B, self.S
        if stage == "anatomy":
            if os.path.isdir(os.path.join(self.SD, S)): return [os.path.join(self.SD, S)]
            return glob.glob(f"{B}/work/{S}_t1synthseg.nii*") or glob.glob(f"{B}/synthseg/{S}_seg.nii*")
        if stage == "registration": return glob.glob(f"{B}/work/{S}_swi2t1.lta") + glob.glob(f"{B}/work/{S}_reg.json")
        if stage == "align": return sorted(glob.glob(f"{B}/work/{S}_t1seg_swispace*") + glob.glob(f"{B}/work/{S}_seg_swispace*") + glob.glob(f"{B}/work/{S}_a2009s_swispace*"))
        if stage == "detect":
            out = [f"{B}/review/{S}_{x}" for x in ("candidates.csv", "candidates.nii.gz", "qc.json", "manifest.json", "score_ai.json")]
            out += glob.glob(f"{B}/review/{S}_excluded.*") + glob.glob(f"{B}/review/{S}_surface_features.*") + [f"{B}/work/{S}_{x}" for x in ("pial_sd.nii.gz", "vessels.nii.gz", "dark.nii.gz", "gen.nii.gz", "dropped.csv", "dropped.nii.gz")]
            return [p for p in out if os.path.exists(p)]
        if stage == "unified": return [p for p in (f"{B}/uscore/features/{S}.json", f"{B}/uscore/reports/{S}.json") if os.path.exists(p)]
        raise KeyError(stage)

    def _swi(self): return next((q for q in (f"{self.B}/data/{self.S}_swi.nii", f"{self.B}/data/{self.S}_swi.nii.gz") if os.path.exists(q)), None)
    def _t1(self): return next((q for q in (f"{self.B}/data/{self.S}_t1.nii.gz", f"{self.B}/data/{self.S}_t1.nii") if os.path.exists(q)), None)

    def mri(self):
        """sha256 of the exact SWI and T1 now in data/ (used by every stage)"""
        s, t = self._swi(), self._t1()
        return dict(swi=_sha(s) if s else None, t1=_sha(t) if t else None)

    def identity(self):
        out = {}
        for k, p in (("swi", self._swi()), ("t1", self._t1())):
            out[k] = image_identity(p) if p else None
        d = os.path.join(self.SD, self.S)
        if os.path.isdir(d):
            fs = dict(path=os.path.relpath(d, self.B))
            bs = os.path.join(d, "scripts", "build-stamp.txt")
            if os.path.exists(bs): fs["version"] = open(bs, errors="replace").read().strip()[:120]
            cmd = os.path.join(d, "scripts", "recon-all.cmd")
            if os.path.exists(cmd): fs["no_v8"] = "-no-v8" in open(cmd, errors="replace").read()
            ld = os.path.join(d, "scripts", "recon-all.done")
            if os.path.exists(ld):
                for ln in open(ld, errors="replace"):
                    if ln.startswith(("END_TIME", "CMDARGS")): fs[ln.split()[0].lower()] = ln.split(None, 1)[1].strip()[:200] if len(ln.split()) > 1 else ""
            out["freesurfer"] = fs
        man = _jl(f"{self.B}/review/{self.S}_manifest.json", {}) or {}
        det = man.get("detect") or {}
        if det: out["detection"] = {k: det.get(k) for k in ("pipeline_version", "build", "run_at", "qc_status") if det.get(k) is not None}
        return out

    # ---- per-stage audit ----
    def audit(self):
        m = self.mri(); act = self.active_manifest() or {}; recorded = act.get("mri", {})
        res = {}; upstream_ok = True
        for st in STAGES:
            fs = self.files(st); r = dict(stage=st, files=[os.path.relpath(f, self.B) for f in fs])
            swi_only = self._t1() is None and not os.path.isdir(os.path.join(self.SD, self.S))
            if not fs and st == "registration" and swi_only: r.update(status=NA, why="no T1: SWI-only route (labels from SynthSeg on the SWI), no registration needed")
            elif not fs: r.update(status=MISSING, why="no output found")
            else:
                bad = [os.path.relpath(f, self.B) for f in fs if os.path.isfile(f) and _readable(f) is False]
                r.update(dict(status=CORRUPT, why="unreadable or truncated: " + ", ".join(bad[:3])) if bad else self._check(st, m, recorded))
            if r["status"] in REUSABLE and not upstream_ok:
                r.update(status=UPSTREAM, why="an earlier stage must be re-run, so this output cannot be reused")
            if r["status"] not in REUSABLE: upstream_ok = False
            r["label"] = LABEL[r["status"]]; res[st] = r
        return dict(study=self.S, mri=m, identity=self.identity(), stages=res, active_run=act.get("run_id"),
                    runs=self.history(), adopted=bool(act))

    def _check(self, st, m, recorded):
        B, S = self.B, self.S
        if m["swi"] is None: return dict(status=INCOMPAT, why="no SWI in data/: the MRI these outputs belong to cannot be confirmed")
        if st == "anatomy":
            d = os.path.join(self.SD, S)
            if os.path.isdir(d):
                need = ["mri/aparc.a2009s+aseg.mgz", "mri/orig.mgz", "mri/brain.mgz"]
                miss = [n for n in need if not os.path.exists(os.path.join(d, n))]
                if miss: return dict(status=INCOMPLETE, why="FreeSurfer did not finish: missing " + ", ".join(miss), kind="freesurfer")
                if glob.glob(os.path.join(d, "scripts", "IsRunning*")):
                    return dict(status=INCOMPLETE, why="FreeSurfer still marked as running (IsRunning file present)", kind="freesurfer")
                bad = [n for n in need if _readable(os.path.join(d, n)) is False]
                if bad: return dict(status=CORRUPT, why="unreadable: " + ", ".join(bad), kind="freesurfer")
                stamp = _jl(os.path.join(d, ".css_input.json"), {})
                t1 = stamp.get("t1_sha256") or recorded.get("t1")
                if t1 and m["t1"] and t1 != m["t1"]: return dict(status=INCOMPAT, why="FreeSurfer was run on a different T1", kind="freesurfer")
                lim = [] if os.path.exists(os.path.join(d, "surf", "lh.pial")) else ["no pial surfaces: surface features unavailable"]
                if not t1: return dict(status=UNKNOWN, why="complete FreeSurfer, but no record of which T1 it came from: confirm before reuse", kind="freesurfer")
                return dict(status=LIMITED if lim else COMPAT, why="complete FreeSurfer from this T1" + ("; " + "; ".join(lim) if lim else ""), kind="freesurfer")
            if m["t1"] is None:
                ok = recorded.get("swi") == m["swi"]
                return dict(status=LIMITED if ok else UNKNOWN, why="SynthSeg on the SWI (no T1): coarse pial surface, surface features unavailable" + ("" if ok else "; not yet linked to this SWI"), kind="swi_synthseg")
            ok = recorded.get("t1") == m["t1"] and m["t1"]
            return dict(status=COMPAT if ok else UNKNOWN, why="SynthSeg segmentation" + ("" if ok else " (T1 it came from not recorded)"), kind="synthseg")
        if st == "registration":
            rj = _jl(f"{B}/work/{S}_reg.json", {}) or {}
            if not os.path.exists(f"{B}/work/{S}_swi2t1.lta"): return dict(status=INCOMPLETE, why="transform file missing")
            if str(rj.get("status", "")).lower() in ("failed", "fail"): return dict(status=INCOMPLETE, why="registration recorded as failed")
            qc = _jl(f"{B}/review/{S}_qc.json", {}) or {}
            if qc.get("registration_ok") is False: return dict(status=INCOMPAT, why="QC: registration not acceptable (label shift)")
        if st == "detect":
            man = _jl(f"{B}/review/{S}_manifest.json", {}) or {}
            ins = (man.get("detect") or {}).get("inputs") or man.get("inputs") or {}
            if not os.path.exists(f"{B}/review/{S}_candidates.csv"): return dict(status=INCOMPLETE, why="candidate table missing")
            for k, v in ins.items():
                h = v.get("sha256") if isinstance(v, dict) else v
                p = os.path.join(B, k) if not os.path.isabs(k) else k
                if h and os.path.exists(p) and _sha(p) != h: return dict(status=INCOMPAT, why=f"input {os.path.basename(k)} changed since detection")
            qc = _jl(f"{B}/review/{S}_qc.json", {}) or {}
            if qc.get("status") == "low_confidence_review": return dict(status=LIMITED, why="detection QC: low confidence (see QC notes)")
            if not ins and recorded.get("swi") != m["swi"]: return dict(status=UNKNOWN, why="detection manifest has no input hashes")
        if st == "unified":
            if not os.path.exists(f"{B}/uscore/reports/{S}.json"): return dict(status=INCOMPLETE, why="report missing (step not finished)")
            f = _jl(f"{B}/uscore/features/{S}.json", {}) or {}
            h = f.get("swi_sha256") or (f.get("inputs") or {}).get("swi_sha256")
            if h and h != m["swi"]: return dict(status=INCOMPAT, why="unified features came from a different SWI")
            cand = f"{B}/review/{S}_candidates.csv"
            if os.path.exists(cand) and os.path.getmtime(f"{B}/uscore/reports/{S}.json") < os.path.getmtime(cand):
                return dict(status=INCOMPAT, why="older than the current candidate list (detection was re-run after it)")
        if recorded and recorded.get("swi") and recorded.get("swi") != m["swi"]:
            return dict(status=INCOMPAT, why="the active run was made from a different SWI")
        return dict(status=COMPAT if recorded.get("swi") == m["swi"] else UNKNOWN,
                    why="outputs present and consistent" + ("" if recorded.get("swi") == m["swi"] else "; no run record links them to this MRI yet (confirm to adopt)"))

    # ---- planning ----
    def plan(self, choice, rerun_from=None, force_anatomy=False):
        """choice: reuse | selective | new. Returns the stages to run, or an error."""
        a = self.audit()
        if not a["adopted"] and any(a["stages"][s]["status"] == UNKNOWN for s in STAGES):
            return dict(ok=False, needs_adopt=True, error="earlier outputs are not linked to this MRI yet: review them and confirm ('adopt') first")
        a = a["stages"]
        first_bad = next((s for s in STAGES if a[s]["status"] not in REUSABLE), None)
        if choice == "reuse":
            if first_bad: return dict(ok=False, error=f"cannot reuse everything: {first_bad} is {a[first_bad]['label']} ({a[first_bad]['why']})", first_bad=first_bad)
            return dict(ok=True, run=[], reuse=STAGES)
        start = "anatomy" if choice == "new" else (rerun_from or first_bad)
        if start is None: return dict(ok=True, run=[], reuse=STAGES, note="all stages reusable; nothing to re-run")
        if start not in STAGES: return dict(ok=False, error=f"unknown stage {start}")
        i = STAGES.index(start)
        if first_bad and STAGES.index(first_bad) < i:
            return dict(ok=False, error=f"{start} depends on {first_bad}, which is {a[first_bad]['label']}: re-run from {first_bad}")
        if start == "anatomy" and a["anatomy"]["status"] in REUSABLE and a["anatomy"].get("kind") == "freesurfer" and not force_anatomy:
            return dict(ok=False, error="a complete FreeSurfer for this T1 exists; it is not re-run unless you confirm a new reconstruction", needs_confirm=True)
        return dict(ok=True, run=STAGES[i:], reuse=STAGES[:i])

    # ---- runs ----
    def history(self):
        out = []
        for m in sorted(glob.glob(os.path.join(self.R, "*", "manifest.json"))):
            d = _jl(m)
            if d: out.append(d)
        return out

    def active_manifest(self):
        a = _jl(os.path.join(self.R, "active.json"), {}) or {}
        return _jl(os.path.join(self.R, a.get("run_id", "-"), "manifest.json")) if a.get("run_id") else None

    def _snapshot(self, run_dir, stages):
        """copy current outputs of the given stages into run_dir/files (FreeSurfer is recorded, never copied)"""
        rec = {}
        for st in stages:
            rec[st] = []
            for f in self.files(st):
                rel = os.path.relpath(f, self.B)
                if st == "anatomy" and os.path.isdir(f):
                    rec[st].append(dict(path=rel, freesurfer_dir=True)); continue
                dst = os.path.join(run_dir, "files", rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(f, dst); rec[st].append(dict(path=rel, sha256=_sha(f)))
        return rec

    def _new_id(self):
        rid = "r" + time.strftime("%Y%m%d-%H%M%S")
        while os.path.exists(os.path.join(self.R, rid)): rid += "x"
        return rid

    def adopt_existing(self, note="outputs found on disk, confirmed by the user"):
        """record what is on disk now as a run (status 'adopted'), without changing any file"""
        if self.history(): return self.active_manifest()
        found = [s for s in STAGES if self.files(s)]
        if not found: return None                          # a new study: nothing to record
        rid = self._new_id(); d = os.path.join(self.R, rid)
        man = dict(run_id=rid, study=self.S, created=time.time(), status="adopted", note=note, mri=self.mri(), identity=self.identity(),
                   stages={s: "found on disk" for s in found}, files=self._snapshot(d, found))
        _js(os.path.join(d, "manifest.json"), man); self.set_active(rid, restore=False)
        return man

    def start_run(self, plan, note="", software=None, rename_fs=True):
        """archive what will be replaced, mark the new run 'running'; the caller then runs plan['run']"""
        self.adopt_existing()
        prev = self.active_manifest() or {}
        rid = self._new_id(); d = os.path.join(self.R, rid); os.makedirs(d)
        if "anatomy" in plan["run"] and rename_fs:              # rename_fs=False: the full pipeline (prep_anat) reuses a finished recon itself
            fs = os.path.join(self.SD, self.S)
            if os.path.isdir(fs):
                aside = f"{fs}__run_{prev.get('run_id', 'previous')}"
                while os.path.exists(aside): aside += "x"
                os.rename(fs, aside)                           # rename only, never delete
                pm = os.path.join(self.R, prev.get("run_id", "-"), "manifest.json")
                if os.path.exists(pm):
                    p = _jl(pm); p["freesurfer_moved_to"] = os.path.relpath(aside, self.B); _js(pm, p)
        man = dict(run_id=rid, study=self.S, created=time.time(), status="running", note=note, mri=self.mri(), identity=self.identity(),
                   parent=prev.get("run_id"), run=plan["run"], reuse=plan["reuse"], software=software or {}, log=os.path.join("runs", self.S, rid, "run.log"),
                   stages={**{s: "reused from " + str(prev.get("run_id")) for s in plan["reuse"]}, **{s: "pending" for s in plan["run"]}})
        _js(os.path.join(d, "manifest.json"), man)
        return man

    def _upd(self, rid, **kw):
        p = os.path.join(self.R, rid, "manifest.json"); m = _jl(p); m.update(kw); _js(p, m); return m

    def stage_state(self, rid, stage, state):
        p = os.path.join(self.R, rid, "manifest.json"); m = _jl(p); m["stages"][stage] = state
        m.setdefault("stage_times", {})[stage] = time.time(); _js(p, m)

    def stage_done(self, rid, stage, ok=True, msg=""): self.stage_state(rid, stage, "done" if ok else "failed: " + msg)

    def finish_run(self, rid, ok=True, msg=""):
        p = os.path.join(self.R, rid, "manifest.json"); m = _jl(p); d = os.path.dirname(p)
        m["status"] = "completed" if ok else "failed"; m["finished"] = time.time(); m["message"] = msg
        if ok:
            fs = os.path.join(self.SD, self.S)
            if os.path.isdir(fs) and not os.path.islink(fs) and m["mri"].get("t1") and not os.path.exists(os.path.join(fs, ".css_input.json")):
                _js(os.path.join(fs, ".css_input.json"), dict(t1_sha256=m["mri"]["t1"], run_id=rid))
            m["files"] = self._snapshot(d, [s for s in STAGES if self.files(s)])
        else:
            restored = self.restore_previous(m)                # the active result stays what it was
            m["restored_from"] = m.get("parent"); m["restored_files"] = restored
        _js(p, m)
        if ok: self.set_active(rid, restore=False)
        return m

    def restore_previous(self, m):
        """after a failure: put back the parent run's archived files for the stages this run touched; remove files of those
        stages that the parent did not have (they were created by the failed run). FreeSurfer is never touched here."""
        par = m.get("parent"); n = 0
        if not par: return 0
        pm = _jl(os.path.join(self.R, par, "manifest.json")) or {}
        for st in m.get("run", []):
            if st == "anatomy": continue
            keep = {it["path"] for it in (pm.get("files") or {}).get(st, []) if not it.get("freesurfer_dir")}
            for f in self.files(st):
                rel = os.path.relpath(f, self.B)
                if rel not in keep and os.path.isfile(f):
                    q = os.path.join(self.R, m["run_id"], "failed_outputs", rel); os.makedirs(os.path.dirname(q), exist_ok=True)
                    shutil.move(f, q)                          # kept for inspection, not deleted
            for rel in keep:
                src = os.path.join(self.R, par, "files", rel)
                if os.path.exists(src):
                    dst = os.path.join(self.B, rel); os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(src, dst); n += 1
        return n

    def set_active(self, rid, restore=True):
        """make rid the active run. With restore, its archived files are copied back into place (the current files are
        already archived in their own run, so nothing is lost)."""
        d = os.path.join(self.R, rid); m = _jl(os.path.join(d, "manifest.json"))
        if not m: raise ValueError(f"no run {rid}")
        if m.get("status") not in ("completed", "adopted"): raise ValueError(f"run {rid} is {m.get('status')}; only completed runs can be active")
        if restore:
            cur = self.active_manifest()
            if cur and cur["run_id"] != rid:
                for st, items in (m.get("files") or {}).items():
                    for it in items:
                        if it.get("freesurfer_dir"):
                            want = os.path.join(self.B, m.get("freesurfer_moved_to") or it["path"])
                            if not os.path.isdir(want): raise ValueError("the FreeSurfer directory of that run is missing")
                for st, items in (m.get("files") or {}).items():
                    for it in items:
                        if it.get("freesurfer_dir"): continue
                        src = os.path.join(d, "files", it["path"]); dst = os.path.join(self.B, it["path"])
                        os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(src, dst)
                if m.get("freesurfer_moved_to"):
                    fs = os.path.join(self.SD, self.S); aside = f"{fs}__run_{cur['run_id']}"
                    if os.path.isdir(fs):
                        while os.path.exists(aside): aside += "x"
                        os.rename(fs, aside); cm = os.path.join(self.R, cur["run_id"], "manifest.json")
                        c = _jl(cm); c["freesurfer_moved_to"] = os.path.relpath(aside, self.B); _js(cm, c)
                    os.rename(os.path.join(self.B, m["freesurfer_moved_to"]), fs); m.pop("freesurfer_moved_to"); _js(os.path.join(d, "manifest.json"), m)
        _js(os.path.join(self.R, "active.json"), dict(run_id=rid, set_at=time.time()))

    def resume_plan(self, rid):
        """an interrupted / failed run is resumed as a NEW run from its first unfinished stage"""
        m = _jl(os.path.join(self.R, rid, "manifest.json")) or {}
        if m.get("status") not in ("interrupted", "failed"): return dict(ok=False, error=f"run {rid} is {m.get('status')}; only interrupted or failed runs can be resumed")
        first = next((s for s in m.get("run", []) if m["stages"].get(s) != "done"), None)
        if first is None: return dict(ok=False, error="every stage of that run finished")
        return self.plan("selective", first, force_anatomy=(first == "anatomy"))

    def recover(self):
        """after an app restart: any run left 'running' becomes 'interrupted' and the previous outputs are restored"""
        n = []
        for p in glob.glob(os.path.join(self.R, "*", "manifest.json")):
            m = _jl(p)
            if m and m.get("status") == "running":
                m["status"] = "interrupted"; m["stages"] = {k: ("interrupted" if v in ("pending", "running") else v) for k, v in m["stages"].items()}
                m["restored_from"] = m.get("parent"); m["restored_files"] = self.restore_previous(m)
                m["message"] = "the app was closed while this run was working; the previous outputs were restored"
                _js(p, m); n.append(m["run_id"])
        return n

READER_PAT = ("_calls", "_final", "_review_log", "_missed", "_excluded_audit", "_robustness")   # + _score*.json except _score_ai.json
def _clone_tree(src, dst):
    """macOS APFS copy-on-write clone of a directory tree (clonefile(2), no subprocess). Returns True if cloned. A clone shares
    blocks only until either side is written: APFS copies a block before modifying it, so writes to the clone never reach the
    original. Not available (other OS / file system / volumes) -> False and the caller makes a normal copy."""
    import platform, ctypes, ctypes.util
    if platform.system() != "Darwin": return False
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        rc = libc.clonefile(os.fsencode(src), os.fsencode(dst), ctypes.c_int(0x0001))   # CLONE_NOFOLLOW
        return rc == 0
    except Exception: return False

def _tree_hashes(root):
    """relative path -> sha256 of every file. A symlink that stays inside the tree is recorded as a link (FreeSurfer uses relative
    links); a symlink that leads OUTSIDE the tree (absolute / ../) is recorded by the content of its target, because the copy
    replaces it with a real file (an isolated copy must not lead back into the source)."""
    out = {}; rr = os.path.realpath(root)
    for d, dirs, files in os.walk(root, followlinks=False):
        for f in files + [x for x in dirs if os.path.islink(os.path.join(d, x))]:
            p = os.path.join(d, f); rel = os.path.relpath(p, root)
            if os.path.islink(p):
                t = os.path.realpath(p)
                if t == rr or t.startswith(rr + "/"): out[rel] = "symlink->" + os.readlink(p)
                elif os.path.isfile(t): out[rel] = _sha(t)
                else: out[rel] = "dangling-or-dir-link->" + os.readlink(p)
            else: out[rel] = _sha(p)
    return out

def _materialize_external_links(root):
    """replace symlinks that lead outside the copied tree by real copies of their targets (files only)"""
    rr = os.path.realpath(root); n = 0
    for d, dirs, files in os.walk(root, followlinks=False):
        for f in files:
            p = os.path.join(d, f)
            if os.path.islink(p):
                t = os.path.realpath(p)
                if not (t == rr or t.startswith(rr + "/")) and os.path.isfile(t):
                    os.remove(p); shutil.copy2(t, p); n += 1
    return n

class ImportError_(RuntimeError): pass

def import_study(src, dst, code, src_subjects=None, _fail_after=None):
    """bring an existing study from another project (e.g. the production ~/css_project) into this experimental project.
    The source is only READ. Every file is first copied into a staging folder inside the experimental project
    (dst/.import_staging/<ID>_<time>/), FreeSurfer included (APFS clone when available and verified, otherwise a normal copy);
    every copy is verified by sha256 against the source; the source is hashed again afterwards and must be unchanged; only then
    are the files moved into place and runs/<ID>/import.json is written LAST as the completion marker. Any failure or
    interruption leaves nothing in place (recover_imports() cleans up after a crash) and is reported, never skipped.
    Reader files (calls, scores, review logs ...) go to historical/<ID>/ for comparison only."""
    import re as _re
    src, dst = os.path.realpath(src), os.path.realpath(dst)
    if src == dst: raise ValueError("source and experimental project are the same folder")
    if not _re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", code): raise ValueError("bad code")
    if os.path.exists(os.path.join(dst, "runs", code, "import.json")) or os.path.exists(os.path.join(dst, "runs", code, "link.json")): raise ValueError(f"{code} is already imported")
    if glob.glob(f"{dst}/data/{code}_*"): raise ValueError(f"{code} already exists in this project")
    plan = []                                                           # (source path, destination path relative to dst, kind)
    for f in sorted(glob.glob(f"{src}/data/{code}_*")):
        if os.path.isfile(f): plan.append((f, f"data/{os.path.basename(f)}", "copied"))
    if not any(r.startswith(f"data/{code}_swi.nii") for _, r, _ in plan): raise ValueError(f"{code}: no SWI in {src}/data")
    for f in sorted(glob.glob(f"{src}/work/{code}_*")):
        if os.path.isfile(f) and not _re.search(r"_R\d+_", os.path.basename(f)): plan.append((f, f"work/{os.path.basename(f)}", "copied"))
    for f in sorted(glob.glob(f"{src}/synthseg/{code}_*")):
        if os.path.isfile(f): plan.append((f, f"synthseg/{os.path.basename(f)}", "copied"))
    for f in sorted(glob.glob(f"{src}/review/{code}_*")):
        if not os.path.isfile(f): continue
        n = os.path.basename(f)[len(code):]
        hist = any(t in n for t in READER_PAT) or (n.startswith("_score") and n != "_score_ai.json")
        plan.append((f, f"historical/{code}/review/{os.path.basename(f)}" if hist else f"review/{os.path.basename(f)}", "historical" if hist else "copied"))
    for sub in ("features", "reports"):
        f = f"{src}/uscore/{sub}/{code}.json"
        if os.path.exists(f): plan.append((f, f"uscore/{sub}/{code}.json", "copied"))
    fs = os.path.realpath(os.path.join(src_subjects or os.path.join(src, "subjects"), code))
    has_fs = os.path.isdir(fs)
    # 1 source state BEFORE (sha256 + size + mtime of every file read)
    before = {s_: (_sha(s_), os.stat(s_).st_size, os.stat(s_).st_mtime) for s_, _, _ in plan}
    fs_before = _tree_hashes(fs) if has_fs else {}
    fs_mt = {r: os.stat(os.path.join(fs, r)).st_mtime for r in fs_before if not str(fs_before[r]).startswith("symlink")}
    stage = os.path.join(dst, ".import_staging", f"{code}_{time.strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(stage); _js(os.path.join(stage, "STAGING.json"), dict(code=code, source=src, started=time.time(), state="copying"))
    rec = dict(source=src, code=code, at=time.time(), copied=[], historical=[], freesurfer=None, verified=False)
    try:
        # 2 copy into staging + verify each copy
        for i, (s_, rel, kind) in enumerate(plan):
            if _fail_after is not None and i >= _fail_after: raise ImportError_("simulated interruption (test)")
            t = os.path.join(stage, "files", rel); os.makedirs(os.path.dirname(t), exist_ok=True); shutil.copy2(s_, t)
            h = _sha(t)
            if h != before[s_][0]: raise ImportError_(f"copy of {rel} does not match its source (sha256)")
            rec[kind].append(dict(path=rel, sha256=h, size=before[s_][1]))
        if has_fs:
            t = os.path.join(stage, "files", "subjects", code); os.makedirs(os.path.dirname(t), exist_ok=True)
            method = "apfs_clone" if _clone_tree(fs, t) else None
            if method is None: shutil.copytree(fs, t, symlinks=True); method = "copy"
            ext = _materialize_external_links(t)
            got = _tree_hashes(t)
            if got != fs_before:
                bad = sorted(set(got.items()) ^ set(fs_before.items()))[:3]
                raise ImportError_(f"FreeSurfer copy does not match the source ({method}): {bad}")
            rec["freesurfer"] = dict(source=fs, method=method, files=len(got), external_links_materialized=ext, verified="sha256 of every file equal to the source",
                                     tree_sha256=hashlib.sha256(json.dumps(sorted(got.items())).encode()).hexdigest())
        # 3 source state AFTER: must be unchanged
        changed = [s_ for s_, v in before.items() if (_sha(s_), os.stat(s_).st_size, os.stat(s_).st_mtime) != v]
        if has_fs:
            if _tree_hashes(fs) != fs_before: changed.append(fs + " (content)")
            changed += [r for r, mt in fs_mt.items() if os.stat(os.path.join(fs, r)).st_mtime != mt]
        if changed: raise ImportError_(f"the source changed during the import: {changed[:3]} - nothing was imported, try again")
        # 4 place (moves inside the experimental project), completion marker last
        _js(os.path.join(stage, "STAGING.json"), dict(code=code, source=src, started=time.time(), state="placing",
                                                      targets=[r for _, r, _ in plan] + ([f"subjects/{code}"] if has_fs else [])))
        for _, rel, _ in plan:
            t = os.path.join(dst, rel); os.makedirs(os.path.dirname(t), exist_ok=True); os.replace(os.path.join(stage, "files", rel), t)
        if has_fs:
            t = os.path.join(dst, "subjects", code)
            if os.path.lexists(t): raise ImportError_(f"subjects/{code} already exists in the experimental project")
            os.makedirs(os.path.dirname(t), exist_ok=True); os.replace(os.path.join(stage, "files", "subjects", code), t)
        rec["verified"] = True; rec["source_unchanged"] = True
        rec["production_split"] = production_split(src, code)       # used only to apply the ranking model exactly where production applies it
        _js(os.path.join(dst, "runs", code, "import.json"), rec)
        shutil.rmtree(stage)
        return rec
    except BaseException as e:
        _undo_import(dst, stage)
        raise ImportError_(f"{code}: import failed and was rolled back - {e}") if not isinstance(e, ImportError_) else ImportError_(f"{code}: import failed and was rolled back - {e}")

def _undo_import(dst, stage):
    """remove what a failed / interrupted import placed (only files listed in its staging record), then the staging folder"""
    st = _jl(os.path.join(stage, "STAGING.json"), {}) or {}
    for rel in st.get("targets", []) if st.get("state") == "placing" else []:
        t = os.path.join(dst, rel)
        if os.path.isdir(t) and not os.path.islink(t): shutil.rmtree(t)
        elif os.path.lexists(t): os.remove(t)
    if os.path.isdir(stage): shutil.rmtree(stage)

def recover_imports(base):
    """at app start: an import cut off by a crash or quit is rolled back and reported"""
    out = []
    for stage in glob.glob(os.path.join(base, ".import_staging", "*")):
        st = _jl(os.path.join(stage, "STAGING.json"), {}) or {}
        code = st.get("code", os.path.basename(stage))
        if os.path.exists(os.path.join(base, "runs", code, "import.json")): shutil.rmtree(stage); continue
        _undo_import(base, stage); out.append(code)
    return out

# ---------------------------------------------------------------- production models (rc2b): confidence + ranking, copied byte-for-byte
PROD_MODELS = ("confidence_model.json", "ranker_model.json")
RANKER_KEYS = ("features", "mean", "sd", "weights", "bias", "impute_median")

def model_compat(base, name):
    """compatibility of a model file in base/review with THIS pipeline: the same checks production applies, made explicit.
    confidence: css_confidence.load (schema css-confidence/1.0 + exact feature list) and whether E30 may be applied (cut_method).
    ranker: structure (keys, equal lengths), training studies, detector builds it was trained on."""
    import sys as _s
    p = os.path.join(base, "review", name)
    if not os.path.exists(p): return dict(present=False, compatible=False, reasons=["not present"])
    out = dict(present=True, sha256=_sha(p), reasons=[], notes=[])
    try: M = json.load(open(p))
    except Exception as e: return dict(out, compatible=False, reasons=[f"not readable JSON: {e}"])
    if name == "confidence_model.json":
        _s.path.insert(0, os.path.join(base, "scripts"))
        try:
            import importlib, css_confidence; importlib.reload(css_confidence); css_confidence.load(p)
            out["compatible"] = True
            out["e30_applicable"] = M.get("cut_method") == "lopo_min"
            out["notes"].append(f"schema {M.get('schema')}, {len(M.get('features', []))} features, cut {M.get('cut_pct')} % ({M.get('cut_method', 'not recorded')}), "
                                f"fitted on {len(M.get('studies', []))} studies" + ("" if out["e30_applicable"] else " - E30 will NOT be applied (cut not lopo_min), exactly as in production"))
        except Exception as e: out.update(compatible=False, reasons=[str(e)])
        finally:
            if os.path.join(base, "scripts") in _s.path: _s.path.remove(os.path.join(base, "scripts"))
    else:
        bad = [k for k in RANKER_KEYS if k not in M]
        if not bad:
            n = len(M["features"])
            bad += [f"{k} has {len(M[k])} values for {n} features" for k in ("mean", "sd", "weights", "impute_median") if len(M[k]) != n]
        out["compatible"] = not bad; out["reasons"] = bad
        out["notes"].append(f"{len(M.get('features', []))} features, trained on {len(M.get('training_studies', []))} studies, detector builds {M.get('detector_builds') or 'not recorded'}")
    return out

def import_production_models(src, dst):
    """copy review/confidence_model.json and review/ranker_model.json from the source project, byte-for-byte, sha256 verified,
    source unchanged. An existing different copy in the experimental project is never overwritten silently: it is reported."""
    rep = {}
    for name in PROD_MODELS:
        s_, d_ = os.path.join(src, "review", name), os.path.join(dst, "review", name)
        r = dict(source=s_, destination=d_)
        if not os.path.exists(s_):
            r.update(status="missing in the source project", parity=False)
            if os.path.exists(d_): r["note"] = "an earlier copy exists in the experimental project and is still used"
            rep[name] = r; continue
        h0, st0 = _sha(s_), os.stat(s_)
        r.update(source_sha256=h0, source_size=st0.st_size, source_mtime=st0.st_mtime)
        if os.path.exists(d_):
            hd = _sha(d_)
            r.update(destination_sha256=hd, status="already present, identical" if hd == h0 else "CONFLICT: the experimental copy differs from the production model (kept; not overwritten)",
                     parity=hd == h0)
        else:
            os.makedirs(os.path.dirname(d_), exist_ok=True); tmp = d_ + ".importing"
            shutil.copy2(s_, tmp); hd = _sha(tmp)
            if hd != h0: os.remove(tmp); r.update(status="FAILED: copy does not match the source (sha256)", parity=False); rep[name] = r; continue
            os.replace(tmp, d_); r.update(destination_sha256=hd, status="copied, verified", parity=True)
        st1 = os.stat(s_)
        if _sha(s_) != h0 or st1.st_mtime != st0.st_mtime: r.update(status="FAILED: the production model changed during the copy", parity=False)
        c = model_compat(dst, name); r["compat"] = c
        if not c.get("compatible"): r["parity"] = False; r["status"] += " - INCOMPATIBLE with this pipeline: " + "; ".join(c.get("reasons", []))
        rep[name] = r
    _js(os.path.join(dst, "review", "production_models.json"), dict(at=time.time(), source=os.path.realpath(src), models=rep))
    return rep

def models_status(base):
    """for the app: recorded import + current compatibility of both models"""
    rec = (_jl(os.path.join(base, "review", "production_models.json"), {}) or {}).get("models", {})
    out = {}
    for name in PROD_MODELS:
        c = model_compat(base, name); r = rec.get(name, {})
        verified = c.get("present") and r.get("source_sha256") == c.get("sha256")
        out[name] = dict(present=c.get("present"), compatible=c.get("compatible"), verified_copy_of_production=bool(verified),
                         import_status=r.get("status", "not imported"), reasons=c.get("reasons", []), notes=c.get("notes", []), sha256=c.get("sha256"))
    return out

def production_split(src, code):
    """the study's split in the source project's labels/study_meta.csv (read only; only the split value is used), as run_css.sh reads it"""
    import csv
    p = os.path.join(src, "labels", "study_meta.csv")
    if not os.path.exists(p): return dict(split="", source="no labels/study_meta.csv in the source project")
    with open(p, newline="") as f:
        for row in csv.DictReader(f):
            if str(row.get("study_id", "")) == code: return dict(split=str(row.get("split", "") or ""), source_sha256=_sha(p))
    return dict(split="", source_sha256=_sha(p), note="study not listed")

link_study = import_study                     # rc1 name kept for callers; rc2 copies FreeSurfer instead of linking it

def studies_on_disk(base):
    """every study with an SWI in data/ or a candidate list, whether the app added it or not (terminal-era studies included)"""
    ids = set()
    for p in glob.glob(f"{base}/data/*_swi.nii*"): ids.add(os.path.basename(p).split("_swi.nii")[0])
    for p in glob.glob(f"{base}/review/*_candidates.csv"): ids.add(os.path.basename(p)[:-len("_candidates.csv")])
    import re
    return sorted(i for i in ids if i and not re.search(r"_R\d+$", i))   # robustness copies (ID_R<k>) are temporary

def recover_all(base):
    out = {}
    for d in glob.glob(os.path.join(base, "runs", "*")):
        r = Study(base, os.path.basename(d)).recover()
        if r: out[os.path.basename(d)] = r
    return out

if __name__ == "__main__":
    import sys
    print(json.dumps(Study(sys.argv[1], sys.argv[2]).audit(), indent=1, default=str))
