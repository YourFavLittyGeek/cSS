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
def link_study(src, dst, code, src_subjects=None):
    """bring an existing study from another project folder (e.g. the production ~/css_project) into this experimental
    project, READ-ONLY for the source: images, registrations, labels and earlier detector outputs are COPIED; the FreeSurfer
    folder is LINKED (symlink, never written - detection only reads it); reader files (calls, scores, review logs) are copied
    to historical/<ID>/ for comparison only and are never read by the pipeline or shown in a blinded read.
    Returns a record of what was copied (with sha256), written to runs/<ID>/link.json."""
    import re as _re
    src, dst = os.path.realpath(src), os.path.realpath(dst)
    if src == dst: raise ValueError("source and experimental project are the same folder")
    if not _re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", code): raise ValueError("bad code")
    if os.path.exists(os.path.join(dst, "runs", code, "link.json")): raise ValueError(f"{code} is already linked")
    if any(os.path.exists(p) for p in glob.glob(f"{dst}/data/{code}_*")): raise ValueError(f"{code} already exists in this project")
    rec = dict(source=src, code=code, at=time.time(), copied=[], historical=[], freesurfer=None)
    def cp(a, b, key):
        os.makedirs(os.path.dirname(b), exist_ok=True); shutil.copy2(a, b); rec[key].append(dict(path=os.path.relpath(b, dst), sha256=_sha(b)))
    for f in sorted(glob.glob(f"{src}/data/{code}_*")):
        if os.path.isfile(f): cp(f, f"{dst}/data/{os.path.basename(f)}", "copied")
    if not glob.glob(f"{dst}/data/{code}_swi.nii*"): raise ValueError(f"{code}: no SWI in {src}/data")
    for f in sorted(glob.glob(f"{src}/work/{code}_*")):
        if os.path.isfile(f) and not _re.search(r"_R\d+_", os.path.basename(f)): cp(f, f"{dst}/work/{os.path.basename(f)}", "copied")
    for f in sorted(glob.glob(f"{src}/review/{code}_*")):
        if not os.path.isfile(f): continue
        n = os.path.basename(f)[len(code):]
        if any(t in n for t in READER_PAT) or (n.startswith("_score") and n != "_score_ai.json"): cp(f, f"{dst}/historical/{code}/review/{os.path.basename(f)}", "historical")
        else: cp(f, f"{dst}/review/{os.path.basename(f)}", "copied")
    for f in sorted(glob.glob(f"{src}/synthseg/{code}_*")):
        if os.path.isfile(f): cp(f, f"{dst}/synthseg/{os.path.basename(f)}", "copied")
    for sub in ("features", "reports"):
        f = f"{src}/uscore/{sub}/{code}.json"
        if os.path.exists(f): cp(f, f"{dst}/uscore/{sub}/{code}.json", "copied")
    fs = os.path.join(src_subjects or os.path.join(src, "subjects"), code)
    if os.path.isdir(fs):
        os.makedirs(f"{dst}/subjects", exist_ok=True); os.symlink(fs, f"{dst}/subjects/{code}"); rec["freesurfer"] = dict(linked_to=fs, read_only=True)
    _js(os.path.join(dst, "runs", code, "link.json"), rec)
    return rec

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
