#!/usr/bin/env python3
"""Interactive cSS reviewer in the browser (v5.4). Research software; expert review required.
usage: review_web.py M12[,M13,...] [--port 8765] [--no-browser] [--reviewer "NAME"]
Starts a server on this computer only (127.0.0.1) and opens the page: a scrollable three-plane viewer (wheel =
slices, Ctrl+wheel or = / - = zoom, right-drag = window / level), the detector's outlines, an evidence meter, the
decision keys (Y cSS, V vein, N normal cortex, A artifact, U unsure, H near ICH), comments, missed-cSS marks, a
ruler, a magnifier and a darkness probe; menu bar and right-click menu. Press ? in the page for all keys. Stop the server with Ctrl+C in the Terminal.

Every decision is saved the moment it is made:
  review/ID_calls.csv              the active reviewer's calls (same format as review_css.py -> mark / score unchanged)
  review/ID_calls_<reviewer>.csv   that reviewer's calls with comment and time
  review/ID_review_log.csv         append-only log of every action (reviewer, time, call, comment, meter value shown)
  review/ID_missed.csv             cSS the detector missed, drawn as a rectangle or with the pen on one slice (centre in
                                   voxel + mm coordinates, plane, slice, outline points, reviewer, note, and what the
                                   detector did there). Reported next to the score; NOT counted in the 0-4 score.
  review/reviewers.json            names entered so far and the last one used

The meter is NOT a probability. It is css_evidence / (css_evidence + vein_evidence) from detect_css.py, lowered for
the review-priority tiers 2-4 and for the v5.3 skull / midline measures (or the trained model's score when
rank_candidates.py has written score_model). It has not been validated against expert labels, and showing it
before the reader decides can bias the call: use the K key (hide) for any read that is used to test the detector.
No data leaves the computer; no packages beyond the pipeline's own are needed."""
import sys, os, json, re, time, threading, subprocess, webbrowser, shutil, base64
import numpy as np, nibabel as nib, pandas as pd
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from scipy import ndimage as ndi
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from css_common import base as _base, save_calls, FP

B = _base()
CALLS = ["cSS", "Vein", "Normal", "Artifact", "Unsure", "Near ICH"]
SEQ_NAMES = {"swi": "SWI", "flair": "FLAIR", "t1": "T1", "t2": "T2", "phase": "Phase (filtered)"}
LOCK = threading.Lock()
slug = lambda s: re.sub(r"[^A-Za-z0-9]+", "_", s.strip()).strip("_") or "reviewer"
now = lambda: time.strftime("%Y-%m-%d %H:%M:%S")


def ai_opinion(r):
    """candidate row -> dict(score 0-1, band, suspect, reason, source). Rule-based, not validated."""
    f = lambda k, d=np.nan: float(r[k]) if k in r and pd.notna(r[k]) else d
    if np.isfinite(f("score_model")):
        s = float(np.clip(f("score_model"), 0, 1)); src = "trained ranking model (score_model)"
    else:
        ce, ve = f("css_evidence", 0.5), f("vein_evidence", 0.5)
        s = ce / max(ce + ve, 1e-6); src = "rule-based evidence (not a probability)"
    tier = int(f("review_priority_rank", 1)); treason = str(r.get("review_priority_reason", "") or "")
    mimic = ""
    if f("skull_frac", 0) >= 0.5: mimic = "artifact (dark skull band)"; s *= 0.4
    elif f("midline_frac", 0) >= 0.5 and f("pial_dist_mm", -1) > 0: mimic = "a midline structure (falx / sinus)"; s *= 0.4
    elif tier == 4: mimic = "a microbleed" if "microbleed" in treason else "artifact (air-bone zone)"; s *= 0.5
    elif tier == 3: mimic = "a vein"; s *= 0.6
    elif tier == 2: mimic = "a mimic (" + treason.split(";")[0] + ")"; s *= 0.8
    elif tier == 5: mimic = "nothing reliable (case quality insufficient)"; s *= 0.3
    s = float(np.clip(s, 0, 1)); band = "green" if s >= 0.66 else "yellow" if s >= 0.33 else "red"
    why = []
    pd_, tub, tram = f("pial_dist_mm"), f("tube_ratio"), f("tram_frac")
    if np.isfinite(pd_): why.append("on the cortex surface" if pd_ <= 0.3 else f"{pd_:.1f} mm out in the sulcal CSF")
    if np.isfinite(tub): why.append("sheet-like" if tub < 0.35 else "tube-like" if tub > 0.45 else "between sheet and tube")
    if np.isfinite(tram) and tram >= 0.4: why.append("dark on both banks of the sulcus")
    if f("vessel_wm_mm", 0) >= 4: why.append("continues into the white matter")
    if f("local_cont_max_mm", 0) >= 10: why.append(f"dark structure runs on for {f('local_cont_max_mm'):.0f} mm")
    if f("artifact_zone", 0) >= 1: why.append("in an air-bone artifact zone")
    if f("cmb_like", 0) >= 1: why.append("small and compact")
    if band == "green": suspect = "I suspect cSS"
    elif band == "yellow": suspect = "Uncertain: could be cSS" + (f" or {mimic}" if mimic else " or normal dark cortex / a vein")
    else: suspect = f"I suspect {mimic}" if mimic else "Probably not cSS (weak evidence: vein or normal cortex more likely)"
    return dict(score=round(s, 2), band=band, suspect=suspect, reason=", ".join(why), source=src, tier=tier)


class Study:
    def __init__(self, sid):
        self.sid = sid
        p = f"{B}/data/{sid}_swi.nii"
        if not os.path.exists(p): raise FileNotFoundError(f"{p} not found")
        self.native = nib.load(p); self.can = nib.as_closest_canonical(self.native)
        self.shape = self.can.shape[:3]; self.vox = [float(v) for v in self.can.header.get_zooms()[:3]]
        # canonical voxel -> native voxel (calls / missed marks are stored in the detector's native indices)
        self.c2n = np.linalg.inv(self.native.affine) @ self.can.affine
        self.df = pd.read_csv(f"{B}/review/{sid}_candidates.csv")
        self.lab = self._grid(f"{B}/review/{sid}_candidates.nii.gz", order=0).astype(np.uint16)
        self.vols = {}; self.meta_seq = {}
        I = self.can.get_fdata().astype(np.float32); self._add("swi", I)
        brain = I > 0; mu, sd = float(np.median(I[brain])), float(1.4826 * np.median(np.abs(I[brain] - np.median(I[brain]))) + 1e-6)
        self.ref_src = "whole brain"
        sp = f"{B}/work/{sid}_seg_swispace.nii.gz"
        if os.path.exists(sp):
            seg = self._grid(sp, order=0); ctx = ((seg >= 1000) | (seg == 3) | (seg == 42)) & brain
            if ctx.sum() > 1000:
                c = np.minimum(I[ctx], np.percentile(I[brain], 99.5)); mu = float(np.median(c))
                sd = float(1.4826 * np.median(np.abs(c - mu)) + 1e-6); self.ref_src = "cortex"
        self.mu, self.sd = mu, sd
        self.paths = {"flair": f"{B}/work/{sid}_flair_swispace.nii.gz", "t1": f"{B}/work/{sid}_t1_swispace.nii.gz",
                      "t2": f"{B}/work/{sid}_t2_swispace.nii.gz", "phase": f"{B}/data/{sid}_phase.nii.gz"}
        self._make_t1()
        self.avail = ["swi"] + [k for k, q in self.paths.items() if os.path.exists(q)]
        # candidate centres (canonical voxels) from the label volume
        ids = self.df.cand_id.astype(int).tolist(); self.centre = {}
        if ids:
            com = ndi.center_of_mass(self.lab > 0, self.lab, ids)
            for i, c in zip(ids, com):
                c = np.round(c).astype(int) if np.all(np.isfinite(c)) else np.array(self.shape) // 2
                if self.lab[tuple(c)] != i:                      # curved object: nearest own voxel to the centre of mass
                    pts = np.argwhere(self.lab == i)
                    if len(pts): c = pts[np.argmin(((pts - c) ** 2).sum(1))]
                self.centre[i] = [int(v) for v in c]
        qp = f"{B}/review/{sid}_qc.json"; self.qc = ""
        if os.path.exists(qp):
            q = json.load(open(qp))
            if q.get("status") not in (None, "ok"): self.qc = f"Case QC {q.get('status')}: " + "; ".join(q.get("reasons", []))

    def _grid(self, path, order=1):
        im = nib.load(path)
        if im.shape[:3] == self.native.shape[:3] and np.allclose(im.affine, self.native.affine, atol=1e-3):
            return nib.as_closest_canonical(im).get_fdata().astype(np.float32)
        from nibabel.processing import resample_from_to
        return resample_from_to(im, (self.shape, self.can.affine), order=order).get_fdata().astype(np.float32)

    def _make_t1(self):
        """T1 on the SWI grid for display (once): the same transform prep_anat.sh uses for the labels"""
        out, lta, sid = self.paths["t1"], f"{B}/work/{self.sid}_swi2t1.lta", self.sid
        if os.path.exists(out) or not os.path.exists(lta) or not shutil.which("mri_vol2vol"): return
        targ = next((q for q in (f"{B}/subjects/{sid}/mri/orig.mgz", f"{B}/data/{sid}_t1.nii.gz") if os.path.exists(q)), None)
        if not targ: return
        r = subprocess.run(["mri_vol2vol", "--mov", f"{B}/data/{sid}_swi.nii", "--targ", targ, "--lta", lta, "--inv",
                            "--o", out], capture_output=True, text=True)
        print(f"{sid}: T1 on the SWI grid " + ("written" if r.returncode == 0 and os.path.exists(out) else "FAILED (T1 not offered)"))

    def _add(self, name, V, signed=False):
        V = np.nan_to_num(V)
        if signed: lo, hi = -np.pi, np.pi
        else:
            nz = V[V > 0]; lo, hi = 0.0, float(np.percentile(nz, 99.9)) if nz.size else 1.0
        U = np.clip((V - lo) / max(hi - lo, 1e-6), 0, 1) * 65535
        nz = U[V != 0] if not signed else U.ravel()
        w = [float(v) for v in (np.percentile(nz, [1, 99]) if nz.size else (0, 65535))]
        if signed: w = [65535 * 0.35, 65535 * 0.65]
        self.vols[name] = U.astype("<u2"); self.meta_seq[name] = dict(lo=lo, hi=hi, win=w, label=SEQ_NAMES[name])

    def volume(self, name):
        if name not in self.vols:
            V = self._grid(self.paths[name], order=0 if name == "phase" else 1)
            if name == "phase":
                a, b = float(V.min()), float(V.max())
                if b - a > 2 * np.pi + 0.5: V = (V - a) / (b - a) * 2 * np.pi - np.pi     # scanner units -> radians
                z = np.exp(1j * V); sg = (4.0 / self.vox[0], 4.0 / self.vox[1], 0)        # homodyne high-pass per slice
                lp = ndi.gaussian_filter(z.real, sg) + 1j * ndi.gaussian_filter(z.imag, sg)
                self._add("phase", np.angle(z * np.conj(lp)).astype(np.float32), signed=True)
            else: self._add(name, V)
        return self.vols[name]

    # ---------- calls ----------
    def rpath(self, reviewer): return f"{B}/review/{self.sid}_calls_{slug(reviewer)}.csv"

    def load_calls(self, reviewer):
        """-> ({cand_id: {call, comment, time}}, note). Matched by fingerprint, so a detector re-run cannot move a call"""
        p, note = self.rpath(reviewer), ""
        if not os.path.exists(p):
            legacy = f"{B}/review/{self.sid}_calls.csv"
            import glob
            if os.path.exists(legacy) and not glob.glob(f"{B}/review/{self.sid}_calls_*.csv"):
                p = legacy; note = "Calls made with the old reviewer were loaded under this name."
            else: return {}, ""
        c = pd.read_csv(p)
        if not len(c) or not all(k in c.columns for k in FP): return {}, note
        C = self.df[["cand_id"] + FP].to_numpy(float); out = {}; lost = 0
        for _, r in c.iterrows():
            d = np.sqrt(((C[:, 1:4] - r[FP[:3]].to_numpy(float)) ** 2).sum(1))
            dv = np.abs(C[:, 4] - float(r.volume_mm3)) / max(float(r.volume_mm3), 1.0)
            ok = np.where((d <= 2.0) & (dv <= 0.15))[0]
            if not len(ok): lost += 1; continue
            cm = r.get("comment", ""); call = r.get("call", "")
            out[int(C[ok[d[ok].argmin()], 0])] = dict(call=call if isinstance(call, str) else "",
                                                     comment=cm if isinstance(cm, str) else "",
                                                     time=r.get("time") if isinstance(r.get("time"), str) else "")
        if lost: note += f" {lost} earlier call(s) match no current candidate (detector re-run) and were left out."
        return out, note.strip()

    def save(self, reviewer, calls, cand_id=None, action="call", ai=None):
        c = self.df.set_index("cand_id")
        rows = [dict(cand_id=k, call=v["call"], comment=v.get("comment", ""), reviewer=reviewer, time=v.get("time", ""),
                     **{f: c.loc[k, f] for f in FP}) for k, v in sorted(calls.items()) if v.get("call") or v.get("comment")]
        pd.DataFrame(rows, columns=["cand_id", "call", "comment", "reviewer", "time"] + FP).to_csv(self.rpath(reviewer), index=False)
        save_calls(B, self.sid, self.df, {k: v["call"] for k, v in calls.items() if v.get("call")})
        if cand_id is not None:
            v = calls.get(cand_id, {}); lp = f"{B}/review/{self.sid}_review_log.csv"; new = not os.path.exists(lp)
            with open(lp, "a") as f:
                if new: f.write("time,reviewer,action,cand_id,call,comment,meter_shown,vox_i,vox_j,vox_k,volume_mm3\n")
                q = lambda s: '"' + str(s).replace('"', "'").replace("\n", " ") + '"'
                f.write(",".join([now(), q(reviewer), action, str(cand_id), q(v.get("call", "")), q(v.get("comment", "")),
                                  "" if ai is None else str(ai)] + [str(c.loc[cand_id, k]) for k in FP]) + "\n")

    # ---------- missed cSS marks ----------
    MCOLS = ["missed_id", "reviewer", "time", "vox_i", "vox_j", "vox_k", "x_mm", "y_mm", "z_mm", "can_i", "can_j", "can_k",
             "comment", "plane", "slice", "shape", "points", "detector_fate"]

    def missed(self):
        p = f"{B}/review/{self.sid}_missed.csv"
        if not os.path.exists(p): return pd.DataFrame(columns=self.MCOLS)
        m = pd.read_csv(p, dtype=str).fillna("")
        for c in self.MCOLS:
            if c not in m.columns: m[c] = ""
        for c in ("missed_id", "can_i", "can_j", "can_k", "vox_i", "vox_j", "vox_k"): m[c] = m[c].astype(float).astype(int)
        return m[self.MCOLS]

    def fate(self, pts):
        """what the detector did with the marked voxels (+/- 1 voxel): shown / excluded (rule) / below a gate / not generated"""
        pts = np.clip(np.round(np.asarray(pts, float)).astype(int).reshape(-1, 3), 0, np.array(self.shape) - 1)
        m = np.zeros(self.shape, bool); m[tuple(pts.T)] = True; m = ndi.binary_dilation(m, iterations=1)
        out = []
        ids = np.unique(self.lab[m]); ids = ids[ids > 0]
        if len(ids): out.append("overlaps shown candidate " + ", ".join(f"#{int(i)}" for i in ids))
        if not hasattr(self, "_xl"):
            xp, dp = f"{B}/review/{self.sid}_excluded.nii.gz", f"{B}/work/{self.sid}_dropped.nii.gz"
            self._xl = self._grid(xp, order=0).astype(int) if os.path.exists(xp) else None
            self._dl = self._grid(dp, order=0).astype(int) if os.path.exists(dp) else None
            xc = f"{B}/review/{self.sid}_excluded.csv"; self._xr = {}
            if os.path.exists(xc):
                x = pd.read_csv(xc)
                if len(x) and "excl_id" in x.columns: self._xr = dict(zip(x.excl_id.astype(int), x.reason.astype(str)))
        if self._xl is not None:
            for i in np.unique(self._xl[m]):
                if i > 0: out.append(f"excluded object {int(i)}: {self._xr.get(int(i), '').split(' (')[0]}")
        if self._dl is not None and (self._dl[m] > 0).any(): out.append("below a generation gate (size / slices / shape)")
        return "; ".join(out) if out else "not generated by the detector (outside the search zone, not dark enough, or no ridge)"

    def missed_edit(self, reviewer, action, d=None):
        d = d or {}; m = self.missed()
        if action == "add":
            strokes = d.get("strokes") or [[d["ijk"]]]
            pts = np.array([q for st in strokes for q in st], float)
            if d.get("shape") == "rect" and len(pts) == 2:                       # fill the rectangle for the fate lookup
                lo, hi = np.floor(pts.min(0)).astype(int), np.ceil(pts.max(0)).astype(int)
                g = np.mgrid[lo[0]:hi[0] + 1, lo[1]:hi[1] + 1, lo[2]:hi[2] + 1].reshape(3, -1).T; fp = g[:: max(1, len(g) // 4000)]
            else: fp = pts
            ijk = pts.mean(0) if len(pts) > 1 else np.array(d["ijk"], float)
            n = (self.c2n @ np.r_[ijk, 1.0])[:3]; w = (self.can.affine @ np.r_[ijk, 1.0])[:3]
            m.loc[len(m)] = [int(m.missed_id.max()) + 1 if len(m) else 1, reviewer, now(), *[int(round(v)) for v in n],
                             *[str(round(float(v), 1)) for v in w], *[int(round(v)) for v in ijk], str(d.get("comment", ""))[:300],
                             str(d.get("plane", "")), str(d.get("slice", "")), str(d.get("shape", "point")),
                             json.dumps([[[round(float(c), 1) for c in q] for q in st] for st in strokes]), self.fate(fp)]
        elif action == "delete": m = m[m.missed_id != int(d["id"])]
        elif action == "comment": m.loc[m.missed_id == int(d["id"]), "comment"] = str(d.get("comment", ""))[:300]
        m.to_csv(f"{B}/review/{self.sid}_missed.csv", index=False)
        return m.to_dict("records")


SCORE_KEYS = ("L_score", "R_score", "multifocality_0_4", "category", "n_sulci_total", "L_sulci", "R_sulci", "L_lines", "R_lines",
              "n_lines_total", "scoring_method", "n_unreviewed", "near_ich_candidates", "infratentorial_accepted")
def _score_json(path):
    try: j = json.load(open(path))
    except Exception: return None
    return {k: j[k] for k in SCORE_KEYS if k in j}

def ai_score(s):
    """the same scoring applied to the detector's green-band candidates (rule-based meter >= 0.66). NOT validated.
    Written to review/ID_score_ai.json only; the reader's score files are not touched. Cached per loaded study."""
    if getattr(s, "_ai", None) is None:
        ids = [int(r.cand_id) for _, r in s.df.iterrows() if ai_opinion(r)["band"] == "green"]
        r = subprocess.run([sys.executable, f"{HERE}/score_css.py", s.sid, "--accept-ids", ",".join(map(str, ids)) or "none", "--tag", "ai"],
                           capture_output=True, text=True, env=dict(os.environ, CSS_BASE=B, PYTHONWARNINGS="ignore"))
        s._ai = dict(_score_json(f"{B}/review/{s.sid}_score_ai.json") or {}, n_green=len(ids), green_ids=ids,
                     error="" if r.returncode == 0 else (r.stderr or r.stdout)[-300:])
    return s._ai

STUDIES = {}; IDS = []
def study(sid):
    if sid not in IDS: raise KeyError(sid)
    with LOCK:
        if sid not in STUDIES:
            STUDIES.clear(); print(f"loading {sid} ...", flush=True); STUDIES[sid] = Study(sid)     # one study in memory
        return STUDIES[sid]

def reviewers(add=None):
    p = f"{B}/review/reviewers.json"; d = dict(names=[], last="")
    if os.path.exists(p):
        try: d = json.load(open(p))
        except Exception: pass
    if add and add.strip():
        add = add.strip(); d["names"] = [add] + [n for n in d["names"] if n != add]; d["last"] = add
        json.dump(d, open(p, "w"), indent=1)
    return d

def acq_info(sid):
    """TE / field strength for the corner text, from the JSON sidecar when there is one (else empty)"""
    for f in (f"{B}/data/{sid}_swi.json", f"{B}/data/{sid}.json"):
        try:
            j = json.load(open(f)); te = j.get("EchoTime"); fs = j.get("MagneticFieldStrength")
            return dict(TE_ms=round(float(te) * (1000 if te < 1 else 1), 1) if te else None, field_T=fs)
        except Exception: pass
    return {}


def safe_name(n, exts=("png", "jpg")):
    n = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(str(n))).strip("._") or "snapshot"
    base, _, ext = n.rpartition(".")
    if not base or ext.lower() not in exts: base, ext = n, exts[0]
    return f"{base}.{ext.lower()}"


def side_check(s):
    """do the FreeSurfer hemisphere labels agree with the image sides? (canonical RAS: higher x index = patient right)"""
    try:
        sw = s.volume("swi"); xs = np.where((sw > 0).any(axis=(1, 2)))[0]; mid = (xs.min() + xs.max()) / 2.0
        n = ag = 0
        for _, r in s.df.iterrows():
            c = s.centre.get(int(r.cand_id)); h = str(r.hemi)[:1].upper()
            if c is None or h not in "LR" or abs(c[0] - mid) < 3: continue
            n += 1; ag += int((c[0] > mid) == (h == "R"))
        return dict(n=n, agree=ag, bad=bool(n >= 3 and ag / n < 0.3))
    except Exception: return dict(n=0, agree=0, bad=False)


def meta(sid, reviewer):
    s = study(sid); calls, note = s.load_calls(reviewer) if reviewer else ({}, "")
    cands = []
    for _, r in s.df.iterrows():
        i = int(r.cand_id); g = lambda k: (None if pd.isna(r[k]) else (float(r[k]) if not isinstance(r[k], str) else r[k])) if k in r else None
        cands.append(dict(id=i, hemi=r.hemi, region=str(r.region).replace("ctx-lh-", "").replace("ctx-rh-", ""),
                          volume=float(r.volume_mm3), centre=s.centre.get(i, [v // 2 for v in s.shape]), vox=s.centre.get(i, [v // 2 for v in s.shape]), ai=ai_opinion(r),
                          feat={k: g(k) for k in ("darkness_z", "pial_dist_mm", "tube_ratio", "tram_frac", "extent_mm", "n_slices",
                                                  "css_evidence", "vein_evidence", "score")}))
    return dict(study=sid, studies=IDS, shape=list(s.shape), vox=s.vox, cands=cands, calls=calls, note=note, qc=s.qc,
                seqs=[dict(key=k, **{a: b for a, b in s.meta_seq.get(k, dict(label=SEQ_NAMES[k])).items()}) for k in s.avail],
                missing_seqs=[SEQ_NAMES[k] for k in ("flair", "t1", "t2", "phase") if k not in s.avail], ai_score=ai_score(s),
                reader_score=_score_json(f"{B}/review/{sid}_score.json") if calls else None,
                final=(json.load(open(f"{B}/review/{sid}_final.json")) if os.path.exists(f"{B}/review/{sid}_final.json") else None),
                ref=dict(mu=s.mu, sd=s.sd, src=s.ref_src), missed=s.missed().to_dict("records"), reviewers=reviewers(),
                call_names=CALLS, side_check=side_check(s), snapdir=f"{B}/review/snapshots/{sid}", acq=acq_info(sid))


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, body, ctype="application/json", code=200):
        if not isinstance(body, (bytes, bytearray, memoryview)): body = json.dumps(body, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)
    def _host_ok(self):
        h = (self.headers.get("Host") or "").split(":")[0]
        return h in ("127.0.0.1", "localhost")
    def do_GET(self):
        if not self._host_ok(): return self._send(dict(error="forbidden host"), code=403)
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/": return self._send(open(os.path.join(HERE, "review_web.html"), "rb").read(), "text/html; charset=utf-8")
            if u.path == "/api/meta": return self._send(meta(q.get("study") or IDS[0], q.get("reviewer", "")))
            if u.path == "/api/vol":
                s = study(q["study"]); return self._send(s.volume(q.get("seq", "swi")).tobytes(order="F"), "application/octet-stream")
            if u.path == "/api/seqmeta":
                s = study(q["study"]); s.volume(q["seq"]); return self._send(s.meta_seq[q["seq"]])
            if u.path == "/api/labels": return self._send(study(q["study"]).lab.astype("<u2").tobytes(order="F"), "application/octet-stream")
            self._send(dict(error="not found"), code=404)
        except Exception as e:
            self._send(dict(error=f"{type(e).__name__}: {e}"), code=500)
    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-CSS") != "1": return self._send(dict(error="forbidden"), code=403)
        u = urlparse(self.path)
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if u.path == "/api/reviewer": return self._send(reviewers(d.get("name", "")))
            s = study(d["study"]); rev = (d.get("reviewer") or "").strip()
            if not rev: return self._send(dict(error="Enter the reviewer name first (upper right)."), code=400)
            if u.path == "/api/snapshot":
                name = safe_name(d.get("name", ""))
                folder = os.path.abspath(os.path.expanduser(str(d.get("folder") or f"{B}/review/snapshots/{s.sid}").replace("{study}", s.sid)))
                os.makedirs(folder, exist_ok=True)
                raw = str(d.get("image", "")); raw = raw.split(",", 1)[1] if raw.startswith("data:") else raw
                img = base64.b64decode(raw)
                if len(img) < 100 or len(img) > 80_000_000: return self._send(dict(error="empty or too large image"), code=400)
                path = os.path.join(folder, name)
                if os.path.exists(path):
                    b0, e0 = os.path.splitext(name); k = 2
                    while os.path.exists(os.path.join(folder, f"{b0}_{k}{e0}")): k += 1
                    path = os.path.join(folder, f"{b0}_{k}{e0}")
                open(path, "wb").write(img)
                if d.get("sidecar"):
                    m = d.get("meta") or {}; c = m.get("cur") or [0, 0, 0]; aff = s.can.affine
                    mm = (aff @ np.array([c[0], c[1], c[2], 1.0]))[:3]
                    lines = [f"study: {s.sid}", f"reviewer: {rev}", f"candidate: {m.get('cand_id')}", f"plane: {m.get('plane')}{' (MIRRORED left-right)' if m.get('mirrored') else ''}  slice: {m.get('slice')}  sequence: {m.get('seq')}",
                             f"voxel xyz: {c[0]} {c[1]} {c[2]}", f"mm xyz (SWI space): {mm[0]:.1f} {mm[1]:.1f} {mm[2]:.1f}", f"call: {m.get('call') or '-'}",
                             f"AI meter (rule-based, not validated): {m.get('meter')}", f"zoom: {m.get('zoom')}", f"saved: {time.strftime('%Y-%m-%d %H:%M:%S')}"]
                    open(os.path.splitext(path)[0] + ".txt", "w").write("\n".join(lines) + "\n")
                return self._send(dict(ok=True, path=path, folder=folder))
            if u.path == "/api/openfolder":
                f = os.path.abspath(os.path.expanduser(str(d.get("path") or "").replace("{study}", s.sid)))
                if not os.path.isdir(f): return self._send(dict(error="folder does not exist yet"), code=400)
                cmd = ["open", f] if sys.platform == "darwin" else ["explorer", f] if os.name == "nt" else ["xdg-open", f]
                try: subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as e: return self._send(dict(error=str(e)), code=500)
                return self._send(dict(ok=True))
            if u.path == "/api/call":
                with LOCK:
                    calls, _ = s.load_calls(rev); cid = int(d["cand_id"]); cur = calls.get(cid, dict(call="", comment=""))
                    if "call" in d:
                        if d["call"] not in CALLS + [""]: return self._send(dict(error="unknown call"), code=400)
                        cur["call"] = d["call"]; cur["time"] = now()
                        if d["call"] and isinstance(cur.get("comment"), str):      # an explicit call confirms an inherited call / answers a hint
                            cur["comment"] = re.sub(r"^\[(inherited|old calls)[^\]]*\]\s*", "", cur["comment"])
                    if "comment" in d: cur["comment"] = str(d["comment"])[:500]
                    calls[cid] = cur
                    if not cur.get("call") and not cur.get("comment"): calls.pop(cid)
                    s.save(rev, calls, cid, d.get("action", "call"), d.get("meter"))
                return self._send(dict(ok=True, calls=calls, saved=now()))
            if u.path == "/api/missed":
                with LOCK: m = s.missed_edit(rev, d["action"], d)
                return self._send(dict(ok=True, missed=m, saved=now()))
            if u.path == "/api/finish":
                calls, _ = s.load_calls(rev); c = {k: v["call"] for k, v in calls.items() if v.get("call")}
                acc = sorted(k for k, v in c.items() if v == "cSS"); ich = sorted(k for k, v in c.items() if v == "Near ICH")
                with LOCK: s.save(rev, calls)
                cmd = [sys.executable, f"{HERE}/mark_css.py", s.sid, ",".join(map(str, acc)) or "none", "--reviewed",
                       ",".join(map(str, sorted(c))) or "none"] + (["--ich", ",".join(map(str, ich))] if ich else [])
                r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, CSS_BASE=B, PYTHONWARNINGS="ignore"))
                res = dict(ok=r.returncode == 0, text=(r.stdout + ("\n" + r.stderr[-1500:] if r.returncode else "")).strip(),
                           counts={k: sum(v == k for v in c.values()) for k in CALLS}, unread=len(s.df) - len(c),
                           missed=s.missed().to_dict("records"), reader_score=_score_json(f"{B}/review/{s.sid}_score.json"),
                           ai_score=ai_score(s))
                if d.get("final"):
                    # final save: one record per study (overwritten by a later final save) + the cohort report
                    lp = f"{B}/review/{s.sid}_review_log.csv"; nrev = 0
                    if os.path.exists(lp):
                        lg = pd.read_csv(lp); nrev = int(((lg.action == "revote") & (lg.reviewer == rev)).sum())
                    fin = dict(study=s.sid, reviewer=rev, saved=now(), reviewer_score=res["reader_score"], ai_score=res["ai_score"],
                               n_candidates=int(len(s.df)), n_read=int(len(c)), n_css=int(len(acc)), n_differ=d.get("n_differ", ""),
                               n_missed=int(len(res["missed"])), n_revoted=nrev, meter_visible=d.get("meter_visible", ""), n_inherited_unconfirmed=d.get("n_inherited_unconfirmed", ""),
                               comparison_shown=bool(d.get("comparison_shown")))
                    json.dump(fin, open(f"{B}/review/{s.sid}_final.json", "w"), indent=1)
                    import css_report
                    out, n, xl = css_report.build(B); res["final"] = fin; res["report"] = f"{out}.csv{xl}"
                return self._send(res)
            self._send(dict(error="not found"), code=404)
        except Exception as e:
            self._send(dict(error=f"{type(e).__name__}: {e}"), code=500)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0].startswith("-"): sys.exit(__doc__)
    IDS = [s for s in a[0].split(",") if s]
    port = int(a[a.index("--port") + 1]) if "--port" in a else 8765
    if "--reviewer" in a: reviewers(a[a.index("--reviewer") + 1])
    for sid in IDS:
        for f in (f"{B}/data/{sid}_swi.nii", f"{B}/review/{sid}_candidates.csv", f"{B}/review/{sid}_candidates.nii.gz"):
            if not os.path.exists(f): sys.exit(f"{sid}: {f} not found - run the detection first")
    for p in range(port, port + 20):
        try: srv = ThreadingHTTPServer(("127.0.0.1", p), H); break
        except OSError: continue
    else: sys.exit(f"no free port between {port} and {port + 19}")
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"cSS reviewer for {', '.join(IDS)}: {url}   (this computer only; Ctrl+C here to stop)", flush=True)
    study(IDS[0])
    if "--no-browser" not in a: threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\nstopped; all decisions were saved as they were made")
