#!/usr/bin/env python3
"""Interactive cSS reviewer in the browser (v5.4). Research software; expert review required.
usage: review_web.py M12[,M13,...] [--port 8765] [--no-browser] [--reviewer "NAME"] [--audit]
Only the detector's SHOWN candidates are listed: objects the exclusion rules removed are never shown (v5.7-E-fix5 default).
  --open    the SECOND LOOK starts opened (AI meter visible). Phase 3A.2: it never skips the blind initial read - the server decides the phase
  --show-excluded  list EVERY rule-excluded object after the candidates (ids 10001.., rule shown, calls in ID_excluded_audit_<name>.csv, never scored)
  --audit   validation-read audit: mix a 20 % sample of the EXCLUDED objects into the list (shuffled numbering) to check the rules
Starts a server on this computer only (127.0.0.1) and opens the page: a scrollable three-plane viewer (wheel =
slices, Ctrl+wheel or = / - = zoom, right-drag = window / level), the detector's outlines, an evidence meter, the
decision keys (Y cSS, V vessel, N normal cortex, A artifact, U unsure, H near ICH), comments, missed-cSS marks, a
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
import sys, os, json, re, time, threading, subprocess, webbrowser, shutil, base64, glob
import numpy as np, nibabel as nib, pandas as pd
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from scipy import ndimage as ndi
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)
from css_common import base as _base, save_calls, FP, norm_call, LABELS, match_one_to_one
import call_ledger as CL      # v5.15: every reviewer kept; shared ID_calls.csv / ID_score.json = EFFECTIVE calls (policy, default newest)
import review_io as RIO       # Phase 3A.1: crash-safe writes, cross-process study locks, append-only reviewer event journals, recovery
import review_blind as RB     # Phase 3A.2: server-enforced blinded initial read (phase from the journal, blinded candidate ids, redaction)
import secrets

B = _base()


def _pm():
    """app/pensieve_move.py (loaded by file path so the app folder never shadows a reviewer module); None if absent"""
    if "pensieve_move" in sys.modules: return sys.modules["pensieve_move"]
    p = os.path.join(ROOT, "app", "pensieve_move.py")
    if not os.path.exists(p): return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pensieve_move", p); m = importlib.util.module_from_spec(spec)
        sys.modules["pensieve_move"] = m; spec.loader.exec_module(m); return m
    except Exception as e:
        sys.modules.pop("pensieve_move", None); sys.stderr.write(f"[reviewer] Pensieve module not loaded: {e}\n"); return None


def _vault():
    try: return json.load(open(f"{B}/app_data/settings.json")).get("vault_mount") or ""
    except Exception: return ""


def away(sid):
    """the study's images were moved to the Pensieve drive after its review (they come back on open)"""
    pm = _pm()
    return bool(sid and pm and pm.in_pensieve(B, sid) and not os.path.exists(f"{B}/data/{sid}_swi.nii"))
CALLS = ["cSS", "Vessel", "Normal", "Artifact", "Unsure", "Near ICH", "Microbleed"]   # v5.7: Microbleed (fine code MB) = not cSS
# v5.17 Quick Add: optional fine label (css_common.LABELS code) recorded WITH a call; it never changes the call's meaning (see label_schema.py)
FINE = {
    "cSS": ("C",),
    "Vessel": ("V", "VS", "VC", "VT", "VX", "PV", "VF", "OV", "TV"),
    "Normal": ("N", "NI", "CA", "SAH", "LN", "HI", "OH", "OA", "OT"),
    "Artifact": ("A", "AM", "SU"),
    "Microbleed": ("MB",),
    "Unsure": ("U",),
    "Near ICH": ("H",)
}
SEQ_NAMES = {"swi": "SWI", "flair": "FLAIR", "t1": "T1", "t2": "T2", "phase": "Phase (filtered)"}
LOCK = threading.Lock()
slug = lambda s: re.sub(r"[^A-Za-z0-9]+", "_", s.strip()).strip("_") or "reviewer"
now = lambda: time.strftime("%Y-%m-%d %H:%M:%S")
AUDIT_OFFSET, AUDIT_FRAC = 10000, 0.20   # v5.7 validation read: excluded objects shown as ids 10000 + excl_id, 20 % sample
SHOW_EXCL = False                         # v5.8.3: --show-excluded = every excluded object listed with its rule
GROUPS = {}                               # app: cohort -> study ids (--groups FILE.json), for the cohort drop-down
START = [""]                              # app: study opened first (--start ID)
OPEN_READ = False                         # v5.8.1: --open = full viewer, no blind validation read
AUDIT_ON = False                          # v5.7-E-fix5: the excluded-object audit sample only with --audit (user: show the final list, exclusions applied)


def primary(sid, set_to=None, if_missing=False):
    """v5.7: the study's primary reviewer (review/ID_primary.json). Only the primary reviewer's calls are written to the
    shared legacy ID_calls.csv / ID_candidates.csv accept column / ID_score.json. Returns the current name ("" = none)."""
    p = f"{B}/review/{sid}_primary.json"
    cur = json.load(open(p)).get("reviewer", "") if os.path.exists(p) else ""
    if set_to and (not if_missing or not cur):
        with RIO.study_lock(B, sid):
            cur = json.load(open(p)).get("reviewer", "") if os.path.exists(p) else ""
            if not if_missing or not cur:
                RIO.journal_append(B, sid, set_to, "primary_set", previous=cur, primary=set_to.strip(), automatic=bool(if_missing))
                RIO.atomic_write_json(p, dict(reviewer=set_to.strip(), set=now())); cur = set_to.strip()
    return cur


def score_path(sid, reviewer):
    """v5.15: every reviewer's OWN score is ID_score_rev_<name>.json; the shared ID_score.json is the score of the EFFECTIVE calls
    (call_ledger policy). Without a reviewer name: the shared file."""
    return f"{B}/review/{sid}_score_rev_{slug(reviewer)}.json" if reviewer and reviewer.strip() else f"{B}/review/{sid}_score.json"


def final_path(sid, reviewer): return f"{B}/review/{sid}_final_{slug(reviewer)}.json"


def load_final(sid, reviewer):
    """the reviewer's own final record; the legacy single ID_final.json only when it was made by this reviewer"""
    for p in (final_path(sid, reviewer), f"{B}/review/{sid}_final.json"):
        if os.path.exists(p):
            try:
                f = json.load(open(p))
                if p.endswith(f"{sid}_final.json") and f.get("reviewer") != reviewer: continue
                return f
            except Exception: pass
    return None


def ai_opinion(r):
    """candidate row -> dict(score 0-1, band, suspect, reason, source). Rule-based, not validated."""
    f = lambda k, d=np.nan: float(r[k]) if k in r and pd.notna(r[k]) else d
    if np.isfinite(f("score_model")):
        s = float(np.clip(f("score_model"), 0, 1)); src = "trained ranking model (score_model)"
    else:
        ce, ve = f("css_evidence", 0.5), f("vein_evidence", 0.5)
        s = ce / max(ce + ve, 1e-6); src = "rule-based evidence (not a probability)"
    tier = int(f("review_priority_rank", 1)); treason = str(r.get("review_priority_reason", "") or "").replace("vein", "vessel")   # v5.24 display: 'Vessel' wording (stored text unchanged)
    mimic = ""
    if f("skull_frac", 0) >= 0.5: mimic = "artifact (dark skull band)"; s *= 0.4
    elif f("midline_frac", 0) >= 0.5 and f("pial_dist_mm", -1) > 0: mimic = "a midline structure (falx / sinus)"; s *= 0.4
    elif tier == 4: mimic = "a microbleed" if "microbleed" in treason else "artifact (air-bone zone)"; s *= 0.5
    elif tier == 3: mimic = "a vessel"; s *= 0.6
    elif tier == 2: mimic = "a mimic (" + treason.split(";")[0] + ")"; s *= 0.8
    elif tier == 5: mimic = "nothing reliable (case quality insufficient)"; s *= 0.3
    mid = ""                       # v5.6.3 hint only (not an exclusion): a thin sheet close to the mid-sagittal plane
    if f("plane_dist_mm", 99) <= 8 and f("cos_plane", 0) >= 0.5 and f("ext_major_mm", 0) >= 15 and not mimic:
        mid = f"lies {f('plane_dist_mm'):.0f} mm from the midline plane as a thin sheet ({f('ext_major_mm'):.0f} mm long): could be the interhemispheric fissure (check coronal / sagittal)"; s *= 0.9
    # v5.7 caps: never green for a blob-like or fissure-like object or a tier 3-5 object (stage-D columns when present)
    blob = f("e23_blob", 0) >= 1 or f("cmb_like", 0) >= 1
    fis = f("fissure_frac", 0) >= 0.5 or bool(mid) or (f("midline_frac", 0) >= 0.5)
    cap = ""
    if blob: cap = "compact blob (microbleed-like)"
    elif fis: cap = "in or next to the interhemispheric fissure"
    elif tier >= 3: cap = f"review tier {tier}"
    if cap: s = min(s, 0.65)
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
    if mid: why.append(mid)
    if cap and band != "red": why.append(f"meter capped below green: {cap}")
    if band == "green": suspect = "I suspect cSS"
    elif band == "yellow": suspect = "Uncertain: could be cSS" + (f" or {mimic}" if mimic else " or normal dark cortex / a vessel")
    else: suspect = f"I suspect {mimic}" if mimic else "Probably not cSS (weak evidence: vessel or normal cortex more likely)"
    return dict(score=round(s, 2), band=band, suspect=suspect, reason=", ".join(why), source=src, tier=tier)



def _pensieve_update(sid):
    """PENSIEVE (architecture integration): replace this study's memory from the authoritative records (journals, call ledger, missed
    marks, prediction ledger). The old direct writes (duplicate rows per save, mismatched candidate ids, blind provenance lost, errors
    swallowed) are gone. A failure is recorded in percival/pensieve/status.json and logged here - the review itself is already saved."""
    try:
        from uengine import pensieve_index as PI
        r = PI.update_study(B, sid)
        if not r.get("ok"): sys.stderr.write(f"[PENSIEVE] {sid}: memory NOT updated - {r.get('error')} (see percival/pensieve/status.json)\n")
        return r
    except Exception as e:
        sys.stderr.write(f"[PENSIEVE] {sid}: memory NOT updated - {type(e).__name__}: {e}\n"); return dict(ok=False, error=str(e))

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
            self._seg = seg.astype(np.int16)                  # kept for side_check (it re-read and re-resampled the labels)
            if ctx.sum() > 1000:
                c = np.minimum(I[ctx], np.percentile(I[brain], 99.5)); mu = float(np.median(c))
                sd = float(1.4826 * np.median(np.abs(c - mu)) + 1e-6); self.ref_src = "cortex"
        self.mu, self.sd = mu, sd
        self.paths = {"flair": f"{B}/work/{sid}_flair_swispace.nii.gz", "t1": f"{B}/work/{sid}_t1_swispace.nii.gz",
                      "t2": f"{B}/work/{sid}_t2_swispace.nii.gz", "phase": f"{B}/data/{sid}_phase.nii.gz"}
        self._make_t1()
        self.avail = ["swi"] + [k for k, q in self.paths.items() if os.path.exists(q)]
        # candidate centres (canonical voxels) from the label volume
        self.centre = candidate_centres(self.lab, self.df.cand_id.astype(int).tolist(), self.shape)
        qp = f"{B}/review/{sid}_qc.json"; self.qc = ""
        if os.path.exists(qp):
            q = json.load(open(qp))
            if q.get("status") not in (None, "ok"): self.qc = f"Case QC {q.get('status')}: " + "; ".join(q.get("reasons", []))

    # ---------- v5.7 validation read: a sample of EXCLUDED objects mixed into the list (never scored) ----------
    def _excluded(self):
        if getattr(self, "_aud_xl", None) is None:
            xp, xn = f"{B}/review/{self.sid}_excluded.csv", f"{B}/review/{self.sid}_excluded.nii.gz"
            xd = pd.read_csv(xp) if os.path.exists(xp) else pd.DataFrame()
            if len(xd) and "excl_id" in xd.columns and os.path.exists(xn): xl = self._grid(xn, order=0).astype(np.int32)
            else: xl, xd = np.zeros(1, np.int32), pd.DataFrame()
            # set _aud_xd BEFORE _aud_xl: a concurrent request tests _aud_xl and then reads _aud_xd (race seen as AttributeError)
            self._aud_xd = xd; self._aud_xl = xl
        return self._aud_xd, self._aud_xl

    def audit_ids(self, reviewer):
        """deterministic 20 % sample of the excluded objects (at least 1 when any), seeded by study + reviewer"""
        xd, _ = self._excluded()
        if SHOW_EXCL: return sorted(int(r.excl_id) for _, r in xd.iterrows()) if len(xd) else []
        if not AUDIT_ON: return []
        if not len(xd): return []
        ids = sorted(int(r.excl_id) for _, r in xd.iterrows() if not str(r.get("reason", "")).lower().startswith("infratentorial"))
        if not ids: return []
        seed = int.from_bytes((self.sid + "|" + slug(reviewer)).encode()[:16].ljust(16, b"_"), "little") % (2 ** 32)
        rng = np.random.default_rng(seed)
        n = max(1, int(round(AUDIT_FRAC * len(ids))))
        return sorted(int(i) for i in rng.choice(ids, size=min(n, len(ids)), replace=False))

    def struct3d(self, cid):
        """v5.9 3-D view data: the whole dark structure of candidate (or excluded object 10000+id) as points in mm around its centre, the cortex surface nearby,
        the object's own core, and the shape measures + plain-language verdict (css_shape.struct_measures). Canonical (RAS+) axes: x right, y anterior, z superior."""
        import css_shape
        if not hasattr(self, "_s3"):
            dp = f"{B}/work/{self.sid}_dark.nii.gz"; sp = f"{B}/work/{self.sid}_seg_swispace.nii.gz"; pp = f"{B}/work/{self.sid}_pial_sd.nii.gz"
            dark = self._grid(dp, order=0) > 0 if os.path.exists(dp) else None
            seg = self._grid(sp, order=0) if os.path.exists(sp) else None
            self._s3 = dict(dark=dark, ctx=((seg >= 1000) & (seg < 3000)) if seg is not None else None, psd=self._grid(pp, order=1) if os.path.exists(pp) else None)
        S = self._s3
        if S["dark"] is None or S["ctx"] is None: return dict(error="the 3-D view needs work/ID_dark.nii.gz and the T1 labels (work/ID_seg_swispace.nii.gz)")
        if cid >= AUDIT_OFFSET:
            xd, xl = self._excluded(); obj_full = self._xl_can == (cid - AUDIT_OFFSET) if hasattr(self, "_xl_can") else None
            return dict(error="3-D view is available for the shown candidates")
        obj_full = self.lab == cid
        if not obj_full.any(): return dict(error="object not found")
        vox = np.array(self.vox); pts = np.argwhere(obj_full); lo = np.maximum(pts.min(0) - np.ceil(22 / vox).astype(int), 0); hi = np.minimum(pts.max(0) + np.ceil(22 / vox).astype(int) + 1, self.shape)
        sl = tuple(slice(a, b) for a, b in zip(lo, hi)); obj = obj_full[sl]
        sm = css_shape.struct_measures(S["dark"][sl], obj, S["ctx"][sl], S["psd"][sl] if S["psd"] is not None else None, vox, 20.0)
        st = css_shape.dark_support(S["dark"][sl], obj, vox, cap_mm=20.0, grow=1)
        cen = (np.argwhere(st).mean(0) if st.any() else np.argwhere(obj).mean(0))
        def pts_mm(m, cap, seed):
            p = np.argwhere(m); 
            if len(p) > cap: p = p[np.random.default_rng(seed).choice(len(p), cap, replace=False)]
            return np.round((p - cen) * vox, 1).tolist()
        ctx = S["ctx"][sl]; edge = ctx & ~ndi.binary_erosion(ctx, iterations=1)
        dd = ndi.distance_transform_edt(~(st | obj), sampling=vox) if (st | obj).any() else None
        near = edge & (dd <= 14) if dd is not None else edge
        others = ((self.lab[sl] > 0) & (self.lab[sl] != cid))
        sm = {k: (None if (isinstance(v, float) and not np.isfinite(v)) else v) for k, v in sm.items()}
        return dict(id=cid, measures=sm, struct=pts_mm(st & ~obj, 1800, 1), core=pts_mm(obj, 900, 2), cortex=pts_mm(near, 2200, 3), others=pts_mm(others, 500, 4),
                    n_struct=int(st.sum()), vox=[float(v) for v in vox])

    def morph3d(self, cid, margin_mm=8.0):
        """3-D morphology analysis of ONE candidate (css_morph3d) on a candidate-local crop of the canonical grid.
        Read-only: the candidate mask, the SWI and every detector file are only read; results are cached per candidate."""
        import css_morph3d as cm, base64 as b64
        key = (cid, round(float(margin_mm), 1))
        if not hasattr(self, "_m3"): self._m3 = {}
        if key in self._m3: return self._m3[key]
        if cid >= AUDIT_OFFSET: return dict(error="3-D analysis is available for the shown candidates")
        full = self.lab == cid
        if not full.any(): return dict(error="object not found")
        vox = np.array(self.vox, float); P0 = np.argwhere(full); mg = np.ceil(margin_mm / vox).astype(int)
        lo = np.maximum(P0.min(0) - mg, 0); hi = np.minimum(P0.max(0) + mg + 1, self.shape); sl = tuple(slice(a, b) for a, b in zip(lo, hi))
        mask = full[sl].copy()
        if not hasattr(self, "_Ican"): self._Ican = self.can.get_fdata(dtype=np.float32)
        img = self._Ican[sl].copy()
        if not hasattr(self, "_m3maps"):
            g = lambda p, o: self._grid(p, order=o) if os.path.exists(p) else None
            seg = g(f"{B}/work/{self.sid}_seg_swispace.nii.gz", 0)
            self._m3maps = dict(psd=g(f"{B}/work/{self.sid}_pial_sd.nii.gz", 1), ves=g(f"{B}/work/{self.sid}_vessels.nii.gz", 0),
                                dark=g(f"{B}/work/{self.sid}_dark.nii.gz", 0), ctx=((seg >= 1000) & (seg < 3000)) if seg is not None else None)
        Mp = self._m3maps
        crop = lambda a, t=None: (a[sl] > 0.5 if t == "b" else a[sl]).copy() if a is not None else None
        psd, ctx, ves, dark = crop(Mp["psd"]), crop(Mp["ctx"], "b"), crop(Mp["ves"], "b"), crop(Mp["dark"], "b")
        res, arr = cm.analyse(mask, vox, img=img, psd=psd, cortex=ctx, vessel=(ves & ~mask) if ves is not None else None)
        if "error" in res: return res
        cen = arr["P_idx"].mean(0)                                      # crop voxel index of the centroid
        rel = lambda idx: np.round((np.asarray(idx, float) - cen) * vox, 2).tolist()
        from scipy.spatial import cKDTree
        tree = cKDTree(arr["P_idx"] * vox); lab_c, _ = ndi.label(mask, cm.S26); comp = lab_c[tuple(arr["P_idx"].T)]
        def mesh_out(v, f):
            if not len(f): return dict(v=[], f=[], vi=[])
            _, nn = tree.query(v); return dict(v=np.round(v - cen * vox, 2).ravel().tolist(), f=f.ravel().tolist(), vi=nn.tolist())
        def other_mesh(m, step=1):
            if m is None or not m.any(): return None
            from skimage.measure import marching_cubes
            try: v, f, _, _ = marching_cubes(np.pad(m.astype(np.float32), 1), 0.5, spacing=tuple(vox), step_size=step)
            except Exception: return None
            v = v - vox; return dict(v=np.round(v - cen * vox, 2).ravel().tolist(), f=f.ravel().tolist())
        out = dict(id=cid, measures=res, vox=vox.tolist(), origin=lo.tolist(), centroid_vox=np.round(lo + cen, 2).tolist(),
                   voxels=dict(p=rel(arr["P_idx"]), idx=(arr["P_idx"] + lo).tolist(), comp=comp.tolist(), gcls=arr["gcls"].tolist(),
                               thick=np.round(arr["thick"], 2).tolist(), spread=np.round(arr["desc"], 2).tolist(),
                               slab=np.clip(((((arr["P_idx"] * vox) - (arr["P_idx"] * vox).mean(0)) @ np.array(res["pca_axes"]).T[:, 0]
                                            - min(c["pos_mm"] for c in res["xsections"])) / max(1e-6, (max(c["pos_mm"] for c in res["xsections"]) - min(c["pos_mm"] for c in res["xsections"])) / max(1, len(res["xsections"]) - 1)) + 0.5).astype(int), 0, len(res["xsections"]) - 1).tolist() if res["xsections"] else []),
                   mesh=mesh_out(*arr["mesh"]), skeleton=rel(arr["sk"]), branch=rel(arr["sk_branch"]))
        if "hess" in arr:
            h = arr["hess"]; out["voxels"].update(hcls=h["cls"].tolist(), htube=np.round(h["tube"], 2).tolist(), hsheet=np.round(h["sheet"], 2).tolist(),
                                                  heig=np.round(h["eig"], 3).tolist(), haxis=np.round(h["axis"], 2).tolist())
        if "footprint" in arr: out["footprint"] = rel(arr["footprint"])
        if "contact" in arr: out["contact"] = rel(arr["contact"])
        if ves is not None and "vessel_conn" in arr:
            out["vessel_mesh"] = other_mesh(ves & ~mask); out["vessel_conn_mesh"] = other_mesh(arr["vessel_conn"])
        if dark is not None:
            near = dark & ~mask & (ndi.distance_transform_edt(~mask, sampling=vox) <= margin_mm)
            if ves is not None: near &= ~ves
            out["dark_mesh"] = other_mesh(near)
        if ctx is not None: out["cortex_mesh"] = other_mesh(ctx, step=2)
        try:                                                            # v5.14-gui: experimental dark core / blooming support (display layers only)
            sys.path.insert(0, os.path.join(B, "unified_score")); sys.path.insert(0, os.path.join(os.path.dirname(HERE), "unified_score"))
            from uscore import core_decompose as _cd
            Dk = _cd.decompose_experimental(mask, img, vox, valid=img != 0)
            if Dk.get("status") in ("ok", "no_core"):
                out["core_pts"] = rel(np.argwhere(Dk["core"])); out["support_pts"] = rel(np.argwhere(Dk["support"]))
                out["core_note"] = dict(label="experimental, not ground truth", core_voxels=int(Dk["core"].sum()), unstable=Dk.get("core_unstable_frac"))
        except Exception as e:
            out["core_note"] = dict(error=str(e)[:200])
        # MRI context: three orthogonal planes through the centroid (window p1-p99 of the crop)
        lo_w, hi_w = np.percentile(img[img > 0], [1, 99]) if (img > 0).any() else (0, 1)
        q = lambda a: np.clip((a - lo_w) / max(hi_w - lo_w, 1e-6) * 255, 0, 255).astype(np.uint8)
        ci = np.round(cen).astype(int); planes = []
        for ax_, nm in ((2, "axial"), (1, "coronal"), (0, "sagittal")):
            sl2 = [slice(None)] * 3; sl2[ax_] = int(ci[ax_]); a2 = q(img[tuple(sl2)])           # 2-D array over the two other axes (u, v)
            uv = [k for k in range(3) if k != ax_]
            planes.append(dict(name=nm, axis=ax_, at_mm=round(float((ci[ax_] - cen[ax_]) * vox[ax_]), 2), uv=uv, nu=int(a2.shape[0]), nv=int(a2.shape[1]),
                               u0=round(float((0 - cen[uv[0]]) * vox[uv[0]] - vox[uv[0]] / 2), 2), u1=round(float((a2.shape[0] - 1 - cen[uv[0]]) * vox[uv[0]] + vox[uv[0]] / 2), 2),
                               v0=round(float((0 - cen[uv[1]]) * vox[uv[1]] - vox[uv[1]] / 2), 2), v1=round(float((a2.shape[1] - 1 - cen[uv[1]]) * vox[uv[1]] + vox[uv[1]] / 2), 2),
                               data=b64.b64encode(np.ascontiguousarray(a2.T).tobytes()).decode()))
        out["planes"] = planes
        out["margin_mm"] = margin_mm
        self._m3[key] = out; return out

    def audit_rows(self, reviewer):
        """(excl_id, volume) of the excluded objects this reviewer may be shown (for the blinded-id mapping)"""
        if not str(reviewer or "").strip(): return []
        xd, _ = self._excluded(); ids = set(self.audit_ids(reviewer))
        return [(int(r.excl_id), float(r.get("volume_mm3", 0) or 0)) for _, r in xd.iterrows() if int(r.excl_id) in ids] if len(xd) else []

    def ctx(self, reviewer):
        return RB.Ctx(B, self, reviewer, self.audit_rows(reviewer))

    # ---------- Phase 3A.3: independent whole-study search for missed cSS (no detector output shown) ----------
    def ws_state(self, reviewer):
        out = dict(started=False, completed=False, detector_seen_before=None, started_at="", completed_at="", n_marks=None)
        if not str(reviewer or "").strip(): return out
        ev, _ = RIO.read_journal(RIO.journal_path(B, self.sid, reviewer))
        for e in ev:
            if e.get("kind") == "whole_study_started" and not out["started"]: out.update(started=True, started_at=e.get("time", ""), detector_seen_before=e.get("detector_seen_before"))
            elif e.get("kind") == "whole_study_completed": out.update(completed=True, completed_at=e.get("time", ""), n_marks=e.get("n_marks"))
        return out

    def ws_start(self, reviewer):
        with RIO.study_lock(B, self.sid):
            st = self.ws_state(reviewer)
            if st["started"]: return st
            ev, _ = RIO.read_journal(RIO.journal_path(B, self.sid, reviewer))
            seen = any(e.get("kind") in ("blind_ids", "call", "comment", "clear", "undo", "revote", "audit_call", "finish", "import", "inherit") for e in ev) \
                or os.path.exists(self.rpath(reviewer))
            RIO.journal_append(B, self.sid, reviewer, "whole_study_started", detector_seen_before=bool(seen),
                               note="whole-study search: no candidate, outline or AI content is shown")
            return self.ws_state(reviewer)

    def ws_complete(self, reviewer):
        with RIO.study_lock(B, self.sid):
            st = self.ws_state(reviewer)
            if not st["started"]: raise RB.BlindError("open the whole-study search first", 409)
            if st["completed"]: return st
            own = self._mread(self.mpath(reviewer)); n = int(((own.status == "active") & (own.context == "whole_study")).sum())
            RIO.journal_append(B, self.sid, reviewer, "whole_study_completed", n_marks=n, none_found=n == 0, detector_seen_before=st["detector_seen_before"])
            return self.ws_state(reviewer)

    def audit_cands(self, reviewer):
        xd, xl = self._excluded(); out = []; revealed = SHOW_EXCL or load_final(self.sid, reviewer) is not None
        for e in self.audit_ids(reviewer):
            r = xd[xd.excl_id == e].iloc[0]; pts = np.argwhere(xl == e)
            if not len(pts): continue
            c = pts.mean(0); c = pts[np.argmin(((pts - c) ** 2).sum(1))]
            out.append(dict(id=AUDIT_OFFSET + e, audit=True, hemi=str(r.get("hemi", "")), region=str(r.get("region", "")).replace("ctx-lh-", "").replace("ctx-rh-", ""),
                            volume=float(r.get("volume_mm3", len(pts) * np.prod(self.vox))), centre=[int(v) for v in c], vox=[int(v) for v in c],
                            ai=ai_opinion(r), feat={}, rule=(str(r.get("reason", "")).split(":")[0] if revealed else "")))
        return out

    def labels(self, reviewer="", audit=False):
        if not audit: return self.lab
        xd, xl = self._excluded(); L = self.lab.copy()
        for e in self.audit_ids(reviewer):
            m = (xl == e) & (L == 0); L[m] = AUDIT_OFFSET + e
        return L

    def extent(self):
        """2026-11-28 ALBUS outline refinement (uengine/imaging/refine.py): every candidate's extent (grown through the detector's dark map,
        <= 5 mm, the rule of the grading mask) on the canonical grid; made once and cached in review/ID_candidates_extent.nii.gz, remade when
        the SWI, the candidate list or the dark map change. None when the detector outputs it needs are missing."""
        if getattr(self, "_ext", None) is not None: return self._ext
        try:
            ue = os.path.join(os.path.dirname(HERE), "unified_engine")
            if ue not in sys.path: sys.path.insert(0, ue)
            from uengine.imaging import refine as RF
            rec = RF.current(B, self.sid) or RF.run(B, self.sid)
            self._ext = self._grid(rec["path"], order=0).astype(np.uint16)
        except Exception as e:
            print(f"[{self.sid}] extent outline not available: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr); self._ext = None
        return self._ext

    def apath(self, reviewer): return f"{B}/review/{self.sid}_excluded_audit_{slug(reviewer)}.csv"

    def load_audit(self, reviewer):
        p = self.apath(reviewer)
        with RIO.study_lock(B, self.sid): RIO.ensure_table(B, self.sid, reviewer, "audit", p, need=("excl_id",))
        if not os.path.exists(p): return {}
        a = pd.read_csv(p); out = {}
        for _, r in a.iterrows():
            out[AUDIT_OFFSET + int(r.excl_id)] = dict(call=norm_call(r.call) if isinstance(r.call, str) else "", comment=r.comment if isinstance(r.get("comment"), str) else "",
                                                     time=r.get("time", "") if isinstance(r.get("time"), str) else "")
        return out

    def save_audit(self, reviewer, calls, cand_id=None, **info):
        xd, _ = self._excluded(); why = dict(zip(xd.excl_id, xd.reason)) if len(xd) else {}
        rows = [dict(excl_id=k - AUDIT_OFFSET, call=v.get("call", ""), comment=v.get("comment", ""), reviewer=reviewer, time=v.get("time", ""),
                     rule=str(why.get(k - AUDIT_OFFSET, "")).split(":")[0]) for k, v in sorted(calls.items()) if k >= AUDIT_OFFSET and (v.get("call") or v.get("comment"))]
        df = pd.DataFrame(rows, columns=["excl_id", "call", "comment", "reviewer", "time", "rule"])
        with RIO.study_lock(B, self.sid):                                    # Phase 3A.1: journal first, then the file (atomic)
            RIO.ensure_table(B, self.sid, reviewer, "audit", self.apath(reviewer), need=("excl_id",))
            v = calls.get(cand_id, {}) if cand_id is not None else {}
            RIO.write_table(B, self.sid, reviewer, "audit", self.apath(reviewer), df, ["excl_id"], "audit_call",
                            excl_id=None if cand_id is None else int(cand_id) - AUDIT_OFFSET, call=v.get("call", ""), comment=v.get("comment", ""), **info)

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
        """-> ({cand_id: {call, comment, time}}, note). Matched by fingerprint, so a detector re-run cannot move a call.
        v5.7: a reviewer name with no file of its own starts EMPTY (earlier calls only through import_calls)."""
        p, note = self.rpath(reviewer), ""
        with RIO.study_lock(B, self.sid):                                    # Phase 3A.1: repair from the journal before reading
            r = RIO.ensure_table(B, self.sid, reviewer, "calls", p)
        if r["detail"]: note = r["detail"] + "."
        if not os.path.exists(p): return {}, note
        return self._read_calls(p, note)

    def import_sources(self, reviewer):
        """files whose calls can be imported: the legacy ID_calls.csv and every other reviewer's file"""
        out = []
        lp = f"{B}/review/{self.sid}_calls.csv"
        if os.path.exists(lp): out.append(dict(key="legacy", label=f"{self.sid}_calls.csv (shared file, {len(pd.read_csv(lp))} calls)"))
        for f in sorted(glob.glob(f"{B}/review/{self.sid}_calls_*.csv")):
            if f == self.rpath(reviewer): continue
            try: c = pd.read_csv(f); nm = str(c.reviewer.dropna().iloc[0]) if "reviewer" in c.columns and c.reviewer.notna().any() else os.path.basename(f)
            except Exception: continue
            out.append(dict(key=os.path.basename(f), label=f"{nm} ({len(c)} calls)"))
        return out

    def import_calls(self, reviewer, key, overwrite=False):
        """copy calls from a source file onto this reviewer's calls (only candidates without a call unless overwrite).
        Imported calls carry the comment marker '[imported from X]' and stay dashed until the same key is pressed."""
        src = f"{B}/review/{self.sid}_calls.csv" if key == "legacy" else f"{B}/review/{os.path.basename(key)}"
        if not os.path.exists(src): raise FileNotFoundError(f"no such calls file: {key}")
        other, _ = self._read_calls(src, ""); mine, _ = self.load_calls(reviewer); n = 0
        tag = "shared file" if key == "legacy" else key.split("_calls_", 1)[-1].rsplit(".", 1)[0]
        for k, v in other.items():
            if not v.get("call") or (k in mine and mine[k].get("call") and not overwrite): continue
            mine[k] = dict(call=v["call"], comment=f"[imported from {tag}] " + re.sub(r"^\[(inherited|old calls|imported)[^\]]*\]\s*", "", v.get("comment", "") or ""),
                           time=now()); n += 1
        with RIO.study_lock(B, self.sid):
            self.save(reviewer, mine, action="import", source=tag, n_imported=n, overwrite=bool(overwrite))
            lp = f"{B}/review/{self.sid}_review_log.csv"
            if not os.path.exists(lp): RIO.append_line(lp, "time,reviewer,action,cand_id,call,comment,meter_shown,vox_i,vox_j,vox_k,volume_mm3")
            RIO.append_line(lp, f'{now()},"{reviewer}",import,,,"{n} calls from {tag}",,,,,')
        return mine, n

    def _read_calls(self, p, note):
        c = pd.read_csv(p)
        if not len(c) or not all(k in c.columns for k in FP): return {}, note
        out = {}; lost = 0; R = c.to_dict("records")
        for dx in match_one_to_one(self.df, c):                              # Phase 3B: the one authoritative matcher (one-to-one)
            if dx["status"] != "matched": lost += 1; continue
            r = R[dx["row"]]; cm = r.get("comment", ""); call = r.get("call", "")
            out[dx["cand_id"]] = dict(call=norm_call(call) if isinstance(call, str) else "",
                                                     comment=cm if isinstance(cm, str) else "",
                                                     time=r.get("time") if isinstance(r.get("time"), str) else "",
                                                     fine=r.get("fine_code") if isinstance(r.get("fine_code"), str) else "")
        if lost: note += f" {lost} earlier call(s) match no current candidate (detector re-run) and were left out."
        return out, note.strip()

    def save(self, reviewer, calls, cand_id=None, action="call", ai=None, **info):
        with RIO.study_lock(B, self.sid):                                    # Phase 3A.1: one writer per study across processes
            return self._save(reviewer, calls, cand_id, action, ai, **info)

    def _save(self, reviewer, calls, cand_id=None, action="call", ai=None, **info):
        RIO.ensure_table(B, self.sid, reviewer, "calls", self.rpath(reviewer))
        c = self.df.set_index("cand_id")
        rows = [dict(cand_id=k, call=v["call"], comment=v.get("comment", ""), reviewer=reviewer, time=v.get("time", ""),
                     **{f: c.loc[k, f] for f in FP}, fine_code=v.get("fine", "")) for k, v in sorted(calls.items()) if v.get("call") or v.get("comment")]
        # v5.17: calls made on candidates of an EARLIER run (no current candidate matches them) are kept unchanged - they are the human
        # history that candidate lineage carries forward or asks you to confirm; before v5.17 the next save dropped them
        old = pd.read_csv(self.rpath(reviewer)) if os.path.exists(self.rpath(reviewer)) else pd.DataFrame()
        if len(old) and all(k in old.columns for k in FP):                    # rows that match no current candidate are kept unchanged
            R = old.to_dict("records")
            rows += [R[dx["row"]] for dx in match_one_to_one(self.df, old) if dx["status"] != "matched"]
        v = calls.get(cand_id, {}) if cand_id is not None else {}
        RIO.write_table(B, self.sid, reviewer, "calls", self.rpath(reviewer),
                        pd.DataFrame(rows, columns=["cand_id", "call", "comment", "reviewer", "time"] + FP + ["fine_code"]), ["cand_id"] + FP, action,
                        cand_id=None if cand_id is None else int(cand_id), call=v.get("call", ""), fine=v.get("fine", ""), comment=v.get("comment", ""),
                        client_meter="" if ai is None else str(ai), **info)
        CL.materialize(B, self.sid, by=reviewer, rescore=False)                  # v5.15: shared ID_calls.csv = effective calls (no re-score per click)

        _pensieve_update(self.sid)                                               # PENSIEVE: derived index rebuilt from the journaled records

        if cand_id is not None:
            v = calls.get(cand_id, {}); lp = f"{B}/review/{self.sid}_review_log.csv"
            if not os.path.exists(lp): RIO.append_line(lp, "time,reviewer,action,cand_id,call,comment,meter_shown,vox_i,vox_j,vox_k,volume_mm3")
            q = lambda s: '"' + str(s).replace('"', "'").replace("\n", " ") + '"'
            RIO.append_line(lp, ",".join([now(), q(reviewer), action, str(cand_id), q(v.get("call", "")), q(v.get("comment", "")),
                                          "" if ai is None else str(ai)] + [str(c.loc[cand_id, k]) for k in FP]))

    # ---------- missed cSS marks (Phase 3A.3: one file per reviewer, tombstones, ids never reused; the shared file is derived) ----------
    MCOLS = ["missed_id", "reviewer", "time", "vox_i", "vox_j", "vox_k", "x_mm", "y_mm", "z_mm", "can_i", "can_j", "can_k",
             "comment", "plane", "slice", "shape", "points", "detector_fate"]
    RCOLS = MCOLS + ["status", "deleted_at", "deleted_by", "context", "read_phase", "ai_visible"]
    DCOLS = MCOLS + ["context", "read_phase", "ai_visible", "source"]          # derived shared file: the old columns first (consumers unchanged)

    def mpath(self, reviewer): return f"{B}/review/{self.sid}_missed_by_{slug(reviewer)}.csv"
    def _mshared(self): return f"{B}/review/{self.sid}_missed.csv"
    def _mlegacy(self): return f"{B}/review/{self.sid}_missed_legacy.csv"
    def _msidecar(self): return f"{B}/review/{self.sid}_missed.derived.json"

    def _mrev_files(self): return sorted(glob.glob(f"{B}/review/{self.sid}_missed_by_*.csv"))

    def _mread(self, p):
        m = pd.read_csv(p, dtype=str, keep_default_na=False) if os.path.exists(p) else pd.DataFrame(columns=self.RCOLS)
        for c in self.RCOLS:
            if c not in m.columns: m[c] = ""
        return m[self.RCOLS]

    def _mlegacy_rows(self, p=None):
        """rows of the pre-3A shared file, parsed by header; rows whose field count does not match the header are left out (reported)"""
        import csv
        p = p or self._mlegacy(); out, bad = [], 0
        if not os.path.exists(p): return out, bad
        with open(p, newline="") as f: R = list(csv.reader(f))
        if not R: return out, bad
        hd = R[0]
        for row in R[1:]:
            if not row: continue
            if len(row) != len(hd): bad += 1; continue
            r = dict(zip(hd, row))
            try: int(float(r.get("missed_id", ""))); [int(float(r.get(k, ""))) for k in ("vox_i", "vox_j", "vox_k")]
            except ValueError: bad += 1; continue
            out.append(r)
        return out, bad

    def _mall_ids(self):
        ids = []
        for p in self._mrev_files(): ids += [int(float(x)) for x in self._mread(p).missed_id if str(x).strip()]
        ids += [int(float(r["missed_id"])) for r in self._mlegacy_rows()[0]]
        for _, e in RIO.study_events(B, self.sid):                             # ids of earlier (3A.1) journaled marks too: never reused
            ids += [int(x) for x in e.get("missed_ids") or [] if str(x).lstrip("-").isdigit()]
        return ids

    def _mpreserve(self, by):
        """the shared file must be the DERIVED one; a pre-3A file is kept as the legacy source, a file changed by another program is kept aside"""
        p = self._mshared()
        if not os.path.exists(p): return
        sc = json.load(open(self._msidecar())) if os.path.exists(self._msidecar()) else None
        cur = open(p, "rb").read()
        if sc and sc.get("sha256") == RIO.sha256_bytes(cur): return
        if sc is None and os.path.exists(self._mlegacy()) and RIO.sha256_file(self._mlegacy()) == RIO.sha256_bytes(cur): return   # preserved by the migration
        who = by or "(missed-lesion storage)"
        if sc is None and not os.path.exists(self._mlegacy()):
            RIO.journal_append(B, self.sid, who, "missed_legacy_preserved", file=os.path.relpath(self._mlegacy(), B), snapshot=cur.decode("utf-8", "replace"),
                               file_sha256=RIO.sha256_bytes(cur), note="pre-3A shared missed-cSS file kept unchanged as the legacy source")
            RIO.atomic_copy(p, self._mlegacy())
        else:
            dst = f"{B}/review/{self.sid}_missed_external_{time.strftime('%Y%m%d_%H%M%S')}.csv"
            RIO.journal_append(B, self.sid, who, "missed_external_preserved", file=os.path.relpath(dst, B), snapshot=cur.decode("utf-8", "replace"),
                               file_sha256=RIO.sha256_bytes(cur), note="the shared missed-cSS file was changed outside the reviewer; kept aside, not used")
            RIO.atomic_copy(p, dst)

    def _mrows(self, legacy_path=None):
        rows = []
        for r in self._mlegacy_rows(legacy_path)[0]: rows.append(dict({c: r.get(c, "") for c in self.MCOLS}, context="", read_phase="", ai_visible="", source="legacy"))
        for p in self._mrev_files():
            for r in self._mread(p).to_dict("records"):
                if r["status"] == "active": rows.append(dict({c: r[c] for c in self.MCOLS}, context=r["context"], read_phase=r["read_phase"], ai_visible=r["ai_visible"], source="reviewer"))
        rows.sort(key=lambda r: int(float(r["missed_id"])))
        return rows

    def _mrebuild(self):
        txt = pd.DataFrame(self._mrows(), columns=self.DCOLS).to_csv(index=False)
        if not (os.path.exists(self._mshared()) and RIO.sha256_file(self._mshared()) == RIO.sha256_bytes(txt.encode())):
            RIO.atomic_write_text(self._mshared(), txt)
        RIO.atomic_write_json(self._msidecar(), dict(sha256=RIO.sha256_bytes(txt.encode()), derived_from=[os.path.basename(p) for p in self._mrev_files()]
                                                     + ([os.path.basename(self._mlegacy())] if os.path.exists(self._mlegacy()) else []), note="derived file - do not edit"))

    def missed(self, by=""):
        """every reviewer's active marks + the legacy marks (the derived shared file), typed for the viewer. Without a reviewer name (anonymous
        view) nothing is written: the rows are assembled in memory."""
        if not str(by or "").strip():
            sh = self._mshared(); sc = os.path.exists(self._msidecar())
            leg = self._mlegacy() if os.path.exists(self._mlegacy()) else (sh if os.path.exists(sh) and not sc else None)
            m = pd.DataFrame(self._mrows(leg) if leg or self._mrev_files() else [], columns=self.DCOLS).astype(str)
        else:
            with RIO.study_lock(B, self.sid):
                self._mpreserve(by)
                for p in self._mrev_files():
                    RIO.ensure_table(B, self.sid, os.path.basename(p)[len(f"{self.sid}_missed_by_"):-4], "missed_by", p, need=("missed_id",))
                self._mrebuild()
            m = pd.read_csv(self._mshared(), dtype=str, keep_default_na=False)
        for c in self.MCOLS:
            if c not in m.columns: m[c] = ""
        for c in ("missed_id", "can_i", "can_j", "can_k", "vox_i", "vox_j", "vox_k"): m[c] = pd.to_numeric(m[c], errors="coerce")
        m = m.dropna(subset=["missed_id", "vox_i", "vox_j", "vox_k"])
        for c in ("missed_id", "can_i", "can_j", "can_k", "vox_i", "vox_j", "vox_k"): m[c] = m[c].fillna(-1).astype(int)
        return m[self.MCOLS + [c for c in ("context", "source") if c in m.columns]]

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

    def _pen_filled(self, strokes, plane, pts):
        """voxels of a closed freehand outline AND its inside, on the drawn slice (canonical grid). The original strokes are stored unchanged;
        this only decides what the detector did with the area the expert enclosed (audit 2026-11-27: the line alone missed a candidate
        lying inside a loop drawn with a margin)."""
        shp = np.array(self.shape[:3]); R = np.zeros(tuple(shp), bool)
        ax = {"sagittal": 0, "coronal": 1, "axial": 2}.get(plane)
        if ax is None:
            flat = [a for a in range(3) if np.ptp(pts[:, a]) < 0.5]; ax = flat[0] if flat else None
        for st in strokes:
            q = np.array([self._mpoint(x) for x in st], float).reshape(-1, 3)
            if len(q) < 2: continue
            q = np.vstack([q, q[:1]])
            for a_, b_ in zip(q[:-1], q[1:]):
                n = int(np.ceil(np.abs(b_ - a_).max() * 2)) + 1
                for t in np.linspace(0, 1, n): R[tuple(np.clip(np.round(a_ + t * (b_ - a_)).astype(int), 0, shp - 1))] = True
        if ax is not None:
            k = int(np.clip(round(float(np.median(pts[:, ax]))), 0, shp[ax] - 1)); sl = [slice(None)] * 3; sl[ax] = k
            R[tuple(sl)] = ndi.binary_fill_holes(R[tuple(sl)])
        g = np.argwhere(R)
        return g[:: max(1, len(g) // 4000)] if len(g) else pts

    def missed_edit(self, reviewer, action, d=None, own_only=True, **info):
        with RIO.study_lock(B, self.sid):                                    # Phase 3A.1: one writer per study across processes
            return self._missed_edit(reviewer, action, d, **info)

    def _mpoint(self, q):
        if not isinstance(q, (list, tuple)) or len(q) != 3: raise RB.BlindError("invalid point", 400)
        try: v = [float(x) for x in q]
        except (TypeError, ValueError): raise RB.BlindError("invalid point", 400)
        if not all(np.isfinite(v)) or any(x < -0.5 or x > s_ - 0.5 for x, s_ in zip(v, self.shape)): raise RB.BlindError("point outside the image", 400)
        return v

    def _missed_edit(self, reviewer, action, d=None, **info):
        """Phase 3A.3: validated; the reviewer's OWN file only; delete = tombstone; ids never reused; journaled; derived shared file rebuilt"""
        d = d or {}
        if action not in ("add", "delete", "comment"): raise RB.BlindError("unknown action", 400)
        self.missed(reviewer)                                                # preserve / repair sources first
        p = self.mpath(reviewer); own = self._mread(p)
        if action == "add":
            strokes = d.get("strokes") or [[d.get("ijk")]]
            if not isinstance(strokes, list) or not strokes or any(not isinstance(st, list) or not st for st in strokes): raise RB.BlindError("invalid outline", 400)
            pts = np.array([self._mpoint(q) for st in strokes for q in st], float)
            if len(pts) > 20000: raise RB.BlindError("outline too large", 400)
            shape = str(d.get("shape", "point")); plane = str(d.get("plane", "")).strip().lower()
            plane = {"0": "axial", "1": "coronal", "2": "sagittal"}.get(plane, plane)   # 2026-11-25: the page sent the plane index - every mark was refused
            if shape not in ("point", "rect", "pen") or plane not in ("", "axial", "coronal", "sagittal"): raise RB.BlindError("invalid shape or plane", 400)
            sl = str(d.get("slice", ""))
            if sl and not sl.lstrip("-").isdigit(): raise RB.BlindError("invalid slice", 400)
            if shape == "rect" and len(pts) == 2:                            # fill the rectangle for the fate lookup
                lo, hi = np.floor(pts.min(0)).astype(int), np.ceil(pts.max(0)).astype(int)
                g = np.mgrid[lo[0]:hi[0] + 1, lo[1]:hi[1] + 1, lo[2]:hi[2] + 1].reshape(3, -1).T; fp = g[:: max(1, len(g) // 4000)]
            elif shape == "pen" and len(pts) >= 3:                           # 2026-11-28: the ENCLOSED area, not only the drawn line
                fp = self._pen_filled(strokes, plane, pts)
            else: fp = pts
            ijk = pts.mean(0); n = (self.c2n @ np.r_[ijk, 1.0])[:3]; w = (self.can.affine @ np.r_[ijk, 1.0])[:3]
            new_id = max(self._mall_ids(), default=0) + 1
            row = dict(missed_id=str(new_id), reviewer=reviewer, time=now(), vox_i=str(int(round(n[0]))), vox_j=str(int(round(n[1]))), vox_k=str(int(round(n[2]))),
                       x_mm=str(round(float(w[0]), 1)), y_mm=str(round(float(w[1]), 1)), z_mm=str(round(float(w[2]), 1)),
                       can_i=str(int(round(ijk[0]))), can_j=str(int(round(ijk[1]))), can_k=str(int(round(ijk[2]))),
                       comment=re.sub(r"[\x00-\x1f]", " ", str(d.get("comment", "")))[:300], plane=plane, slice=sl, shape=shape,
                       points=json.dumps([[[round(float(c), 1) for c in q] for q in st] for st in strokes]), detector_fate=self.fate(fp), status="active",
                       deleted_at="", deleted_by="", context=info.pop("context", "candidate_review"), read_phase=str(info.get("read_phase", "")),
                       ai_visible=str(info.get("ai_visible", "")))
            own = pd.concat([own, pd.DataFrame([row])], ignore_index=True); changed = [row]
        else:
            try: mid = int(d.get("id"))
            except (TypeError, ValueError): raise RB.BlindError("invalid mark id", 400)
            hit = own.index[(own.missed_id.astype(str) == str(mid)) & (own.status == "active")]
            if not len(hit):
                if any(int(float(r["missed_id"])) == mid for r in self._mlegacy_rows()[0]): raise RB.BlindError("a mark recorded before Phase 3A is kept as recorded", 400)
                raise RB.BlindError("no such missed-cSS mark of yours", 400)
            i = hit[0]
            if action == "delete": own.loc[i, ["status", "deleted_at", "deleted_by"]] = ["deleted", now(), reviewer]
            else: own.loc[i, "comment"] = re.sub(r"[\x00-\x1f]", " ", str(d.get("comment", "")))[:300]
            changed = [own.loc[i].to_dict()]
        RIO.ensure_table(B, self.sid, reviewer, "missed_by", p, need=("missed_id",))
        RIO.write_table(B, self.sid, reviewer, "missed_by", p, own[self.RCOLS], ["missed_id"], f"missed_{action}",
                        missed_ids=[int(float(r["missed_id"])) for r in changed], rows=changed, **info)
        self._mrebuild()
        return self.missed(reviewer).to_dict("records")


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
# v5.20 display labels from the Percival app (in memory, never written to disk): Standard = accession number, Incognito = code.
# Run on its own (no label map) the reviewer shows the study keys as before.
# (named STUDY_LABELS: 'LABELS' is css_common's fine-label table, used by meta() - v5.23 fix of the v5.20 name clash that broke /api/meta)
try: STUDY_LABELS = json.loads(os.environ.get("CSS_STUDY_LABELS", "") or "{}")
except Exception: STUDY_LABELS = {}
BUILDING = {}                      # sid -> threading.Event while a background preload builds it
def study(sid):
    """the open study (and at most one preloaded next study) in memory. 2026-11-25: while the reviewer reads one study, the
    next one of its cohort is prepared in the background, so "Next patient" opens without the loading wait."""
    if sid not in IDS: raise KeyError(sid)
    ev = BUILDING.get(sid)
    if ev is not None: ev.wait(300)                              # being preloaded right now: wait for it, do not build twice
    with LOCK:
        if sid not in STUDIES:
            print(f"loading {sid} ...", flush=True); st = Study(sid)
            for k in [k for k in STUDIES if k != sid]: STUDIES.pop(k)
            STUDIES[sid] = st
        else:
            for k in [k for k in STUDIES if k != sid]: STUDIES.pop(k)   # the other entry was the preload of this one
        s = STUDIES[sid]
    _preload_next(sid)
    return s


def _next_of(sid):
    g = next((v for v in GROUPS.values() if sid in v), None)
    lst = [x for x in g if x in IDS] if g else list(IDS)
    i = lst.index(sid) if sid in lst else -1
    return lst[i + 1] if 0 <= i < len(lst) - 1 else None


def _preload_next(sid):
    nxt = _next_of(sid)
    if not nxt or nxt in STUDIES or nxt in BUILDING or away(nxt) or os.environ.get("CSS_NO_PRELOAD") == "1": return
    ev = threading.Event(); BUILDING[nxt] = ev
    def run():
        try:
            st = Study(nxt)
            with LOCK:
                if sid in STUDIES and nxt not in STUDIES: STUDIES[nxt] = st     # keep it only while sid is still the open study
        except Exception as e:
            sys.stderr.write(f"[reviewer] preload of the next study failed (it loads when opened): {type(e).__name__}: {e}\n")
        finally:
            BUILDING.pop(nxt, None); ev.set()
    threading.Thread(target=run, daemon=True, name=f"preload-{nxt}").start()

def reviewers(add=None):
    p = f"{B}/review/reviewers.json"; d = dict(names=[], last="")
    if os.path.exists(p):
        try: d = json.load(open(p))
        except Exception: pass
    if add and add.strip():
        add = add.strip(); d["names"] = [add] + [n for n in d["names"] if n != add]; d["last"] = add
        with RIO.project_lock(B, "reviewers"): RIO.atomic_write_json(p, d)
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


def candidate_centres(lab, ids, shape):
    """canonical-voxel centre of every candidate: the rounded centre of mass, or - for a curved object whose centre is not
    its own voxel - the nearest own voxel to it. 2026-11-25: computed inside each candidate's bounding box (one
    find_objects pass) instead of whole-volume scans (scipy center_of_mass + argwhere per curved candidate took 20 s on a
    512x512x172 SWI); same result."""
    out = {}
    if not ids: return out
    objs = ndi.find_objects(lab, max_label=max(ids))
    for i in ids:
        sl = objs[i - 1] if 0 < i <= len(objs) else None
        if sl is None: out[i] = [int(v) for v in np.array(shape) // 2]; continue
        sub = lab[sl] == i
        off = np.array([s.start for s in sl])
        pts = np.argwhere(sub) + off                                     # whole-volume coordinates (same rounding as before)
        c = np.round(pts.mean(0)).astype(int)
        if lab[tuple(c)] != i:
            c = pts[np.argmin(((pts - c) ** 2).sum(1))]
        out[i] = [int(v) for v in c]
    return out


def side_check(s):
    if getattr(s, "_side", None) is None: s._side = _side_check(s)       # 2026-11-25: once per loaded study (4 s on every /api/meta)
    return s._side


def _side_check(s):
    """v5.7: do the FreeSurfer hemisphere labels agree with the image sides? World coordinates (RAS, x+ = patient right):
    (1) the left-labelled tissue must lie at smaller x than the right-labelled tissue; (2) each candidate's centre must lie
    on the side of the mid-point between the two hemisphere centroids that its hemisphere label says."""
    try:
        sp = f"{B}/work/{s.sid}_seg_swispace.nii.gz"
        if not os.path.exists(sp): return dict(n=0, agree=0, bad=False, labels_ok=None)
        seg = getattr(s, "_seg", None)
        seg = (seg if seg is not None else s._grid(sp, order=0)).astype(np.int32)[::2, ::2, ::2]   # every 2nd voxel: centroids only
        A = s.can.affine
        L = ((seg >= 1000) & (seg < 2000)) | (seg == 2) | (seg == 3); Rt = (seg >= 2000) | (seg == 41) | (seg == 42)
        if L.sum() < 125 or Rt.sum() < 125: return dict(n=0, agree=0, bad=False, labels_ok=None)
        wx = lambda m: float((A @ np.r_[np.argwhere(m).mean(0) * 2, 1.0])[0])
        xl, xr = wx(L), wx(Rt); mid = (xl + xr) / 2; labels_ok = bool(xl < xr)
        n = ag = 0
        for _, r in s.df.iterrows():
            c = s.centre.get(int(r.cand_id)); h = str(r.hemi)[:1].upper()
            if c is None or h not in "LR": continue
            x = float((A @ np.r_[c, 1.0])[0])
            if abs(x - mid) < 3: continue
            n += 1; ag += int((x > mid) == (h == "R"))
        return dict(n=n, agree=ag, bad=bool((n >= 3 and ag / n < 0.3) or not labels_ok), labels_ok=labels_ok,
                    left_x_mm=round(xl, 1), right_x_mm=round(xr, 1))
    except Exception as e: return dict(n=0, agree=0, bad=False, labels_ok=None, error=str(e))


def _usafe(o):
    """NaN / inf -> None recursively (NaN is not valid JSON)"""
    if isinstance(o, float): return o if np.isfinite(o) else None
    if isinstance(o, dict): return {k: _usafe(v) for k, v in o.items()}
    if isinstance(o, list): return [_usafe(v) for v in o]
    return o


def uscore_report(study, cid):
    """v5.14-gui: the experimental unified-score report of one candidate, read from $CSS_BASE/uscore/reports (never written here)."""
    for f in (f"{B}/uscore/reports/{study}.json",):
        if os.path.exists(f):
            for r in json.load(open(f)).get("reports", []):
                if int(r["cand_id"]) == cid: return _usafe(r)
    f = f"{B}/uscore/reports/candidates.json"
    if os.path.exists(f):
        for r in json.load(open(f)):
            if r["study"] == study and int(r["cand_id"]) == cid: return _usafe(r)
    return dict(available=False)


def meta(sid, reviewer, mode=""):
    """Phase 3A.2: the full payload only in the second look; during the blind initial read every AI field is replaced / removed, other
    reviewers' data are left out and candidates carry blinded ids (review_blind)."""
    if mode == "wholestudy": return _meta_wholestudy(sid, reviewer)
    s = study(sid); ctx = s.ctx(reviewer); d = _meta_full(sid, reviewer, mode, s, blind=ctx.blind)
    d.update(blind=ctx.blind, read_phase=dict(ctx.ph))
    if not ctx.blind: return d
    d["cands"] = sorted((RB.redact_cand(c, ctx) for c in d["cands"]), key=lambda c: c["id"])
    d.update(calls=RB.redact_calls(d["calls"], ctx), percival=None, ai_score=None, calls_rule="", import_sources=[],
             missed=RB.redact_missed(d["missed"], ctx), reader_score=RB.redact_score(d["reader_score"]), final=RB.redact_final(d["final"]))
    return d


def _meta_wholestudy(sid, reviewer):
    """Phase 3A.3: the independent whole-study search - images only: no candidate, outline, call, score or AI content"""
    s = study(sid); st = s.ws_start(reviewer) if str(reviewer or "").strip() else s.ws_state(reviewer)
    d = _meta_full(sid, reviewer, "", s, blind=True)
    own = [r for r in d["missed"] if str(r.get("reviewer", "")).strip() == str(reviewer or "").strip()]
    d.update(cands=[], calls={}, percival=None, ai_score=None, calls_rule="", import_sources=[], reader_score=None, final=None, note="",
             missed=[{k: r.get(k, "") for k in RB.MISSED_KEEP} for r in own], blind=True, whole_study=st, read_phase=dict(phase="whole_study"))
    return d


def _meta_full(sid, reviewer, mode, s, blind=False):
    calls, note = s.load_calls(reviewer) if reviewer else ({}, "")
    audit = (mode == "validation" or SHOW_EXCL) and bool(reviewer)
    if audit: calls.update(s.load_audit(reviewer))
    cands = []
    for _, r in s.df.iterrows():
        i = int(r.cand_id); g = lambda k: (None if pd.isna(r[k]) else (float(r[k]) if not isinstance(r[k], str) else r[k])) if k in r else None
        cands.append(dict(id=i, hemi=r.hemi, region=str(r.region).replace("ctx-lh-", "").replace("ctx-rh-", ""),
                          volume=float(r.volume_mm3), centre=s.centre.get(i, [v // 2 for v in s.shape]), vox=s.centre.get(i, [v // 2 for v in s.shape]), ai=ai_opinion(r),
                          conf=g("confidence_pct"), conf_why=g("confidence_why") or "",
                          feat={k: g(k) for k in ("darkness_z", "pial_dist_mm", "tube_ratio", "tram_frac", "extent_mm", "n_slices",
                                                  "css_evidence", "vein_evidence", "score")}))
    if audit: cands += s.audit_cands(reviewer)
    up = "" if blind else f"{B}/percival/scores/{sid}.json"                                # v5.24 store (before: unified_engine/percival/, migrated by the app)
    if not blind and not os.path.exists(up): up = f"{B}/unified_engine/percival/scores/{sid}.json"                # v5.22 Percival Score of the app's local model (display only, an AI prediction)
    try: percival = json.load(open(up)) if os.path.exists(up) else None
    except Exception: percival = None
    return dict(study=sid, studies=IDS, labels={k: STUDY_LABELS[k] for k in IDS if k in STUDY_LABELS}, percival=percival, groups=GROUPS, shape=list(s.shape), vox=s.vox, cands=cands, calls=calls, mode="validation" if audit else "", open_read=OPEN_READ, note=note, qc=s.qc,
                seqs=[dict(key=k, **{a: b for a, b in s.meta_seq.get(k, dict(label=SEQ_NAMES[k])).items()}) for k in s.avail],
                missing_seqs=[SEQ_NAMES[k] for k in ("flair", "t1", "t2", "phase") if k not in s.avail], ai_score=None if blind else ai_score(s),
                reader_score=(_score_json(score_path(sid, reviewer)) if calls else None),
                final=load_final(sid, reviewer) if reviewer else None, primary=primary(sid), calls_rule="" if blind else CL.effective(B, sid)["rule_text"],
                import_sources=s.import_sources(reviewer) if reviewer else [],
                ref=dict(mu=s.mu, sd=s.sd, src=s.ref_src), missed=s.missed().to_dict("records"), reviewers=reviewers(),
                call_names=CALLS, fine_labels={k: [[c, LABELS[c][0]] for c in v] for k, v in FINE.items()}, side_check=side_check(s), snapdir=f"{B}/review/snapshots/{sid}", acq=acq_info(sid))


def second_look(sid):
    """2026-11-25 LUMOS second look: suggestions of possible missed cSS for this study, asked from the Percival app (it owns the model and
    the activation gate). AI content: refused during a blind initial read (ROUTES)."""
    port = os.environ.get("CSS_APP_PORT", "")
    if not port.isdigit(): return dict(active=False, reasons=["the reviewer was not started from the Percival app"])
    try:
        import urllib.request, urllib.parse
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/second_look?code={urllib.parse.quote(sid)}", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return dict(active=False, reasons=[f"the Percival app did not answer ({type(e).__name__})"])


def albus_marks(sid):
    """2026-11-25 ALBUS's re-detection of this study's missed-cSS marks (outline + measurements summary), asked from the Percival app.
    Detector output: refused during a blind initial read (ROUTES)."""
    port = os.environ.get("CSS_APP_PORT", "")
    if not port.isdigit(): return dict(state="unavailable", marks={}, note="the reviewer was not started from the Percival app")
    try:
        import urllib.request, urllib.parse
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/albus_marks?code={urllib.parse.quote(sid)}", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return dict(state="unavailable", marks={}, note=f"the Percival app did not answer ({type(e).__name__})")


CONF_COLS = ["missed_id", "object_sha", "status", "reviewer", "time", "read_phase"]


def albus_confirm(sid, reviewer, d, **info):
    """the reviewer says ALBUS's outline of a missed-cSS mark is correct / wrong -> review/ID_missed_confirm_by_<reviewer>.csv (own file,
    the latest answer per mark and object). Only confirmed outlines teach NOX and PERCIVAL."""
    try: mid = int(d.get("missed_id"))
    except (TypeError, ValueError): raise RB.BlindError("invalid mark", 400)
    st = str(d.get("status", "")); sha = str(d.get("object_sha", ""))
    if st not in ("correct", "wrong") or not re.fullmatch(r"[0-9a-f]{16}", sha): raise RB.BlindError("invalid answer", 400)
    p = f"{B}/review/{sid}_missed_confirm_by_{slug(reviewer)}.csv"
    with RIO.study_lock(B, sid):
        df = pd.read_csv(p, dtype=str).fillna("") if os.path.exists(p) else pd.DataFrame(columns=CONF_COLS)
        df = df[~((df["missed_id"] == str(mid)) & (df["object_sha"] == sha))]
        df = pd.concat([df, pd.DataFrame([dict(missed_id=str(mid), object_sha=sha, status=st, reviewer=reviewer, time=now(),
                                               read_phase=str(info.get("read_phase", "")))])], ignore_index=True)[CONF_COLS]
        tmp = p + ".tmp"; df.to_csv(tmp, index=False); os.replace(tmp, p)
    return df.to_dict("records")


REJ_COLS = ["key", "model", "p", "vox_i", "vox_j", "vox_k", "reviewer", "time", "read_phase", "ai_visible"]


def lumos_reject(sid, reviewer, d, **info):
    """the reviewer says a LUMOS suggestion is not cSS -> review/ID_lumos_rejects_by_<reviewer>.csv (own file, one row per suggestion;
    a later answer replaces the earlier one). LUMOS learns these as 'not cSS' image examples."""
    key = str(d.get("key", ""))
    if not re.fullmatch(r"spot_\d{1,4}", key): raise RB.BlindError("invalid suggestion", 400)
    v = d.get("vox") or [0, 0, 0]
    try: v = [int(x) for x in v][:3]
    except (TypeError, ValueError): raise RB.BlindError("invalid suggestion", 400)
    p = f"{B}/review/{sid}_lumos_rejects_by_{slug(reviewer)}.csv"
    with RIO.study_lock(B, sid):
        df = pd.read_csv(p, dtype=str).fillna("") if os.path.exists(p) else pd.DataFrame(columns=REJ_COLS)
        model = re.sub(r"[^\w.-]", "", str(d.get("model", "")))[:20]
        df = df[~((df["key"] == key) & (df["model"] == model))]
        row = dict(key=key, model=model, p=str(round(float(d.get("p") or 0), 3)), vox_i=str(v[0]), vox_j=str(v[1]), vox_k=str(v[2]),
                   reviewer=reviewer, time=now(), read_phase=str(info.get("read_phase", "")), ai_visible=str(info.get("ai_visible", "")))
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)[REJ_COLS]
        tmp = p + ".tmp"; df.to_csv(tmp, index=False); os.replace(tmp, p)
    return df.to_dict("records")


def viewer_ident(sid):
    """2026-11-25: name / MRN / accession for the image overlay - asked from the Percival app for every request (Standard + vault readable:
    the identifiers; Incognito / locked: the study code). Only these keys are passed on; nothing is cached on disk or logged. Without the app
    (reviewer started by hand) the study code is shown."""
    port = os.environ.get("CSS_APP_PORT", "")
    if not port.isdigit(): return dict(mode="incognito", code=sid)
    try:
        import urllib.request, urllib.parse
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/viewer_ident?code={urllib.parse.quote(sid)}", timeout=2) as r:
            d = json.loads(r.read().decode())
        if d.get("mode") == "standard":
            return dict(mode="standard", code=str(d.get("code") or sid), name=str(d.get("name") or ""), mrn=str(d.get("mrn") or ""),
                        accession=str(d.get("accession") or ""))
        return dict(mode=d.get("mode") if d.get("mode") in ("incognito", "locked") else "incognito", code=str(d.get("code") or sid))
    except Exception:
        return dict(mode="incognito", code=sid)


# Phase 3A.2: every route and what the blind initial read does with it. A route missing here is not served (tests compare this table with
# the handler code). static / image / settings: no candidate or AI content. redacted: served with AI content removed and blinded ids.
# refused: not served during the blind read. write: translated (blinded id -> candidate) and journaled with the server's read phase.
ROUTES = {("GET", "/"): "static", ("GET", "/morph3d.js"): "static", ("GET", "/api/vset"): "settings", ("POST", "/api/vset"): "settings",
          ("POST", "/api/reviewer"): "settings", ("GET", "/api/vol"): "image", ("GET", "/api/seqmeta"): "image",
          ("GET", "/api/meta"): "redacted", ("GET", "/api/labels"): "redacted", ("GET", "/api/struct3d"): "refused", ("GET", "/api/uscore"): "refused",
          ("GET", "/api/morph3d"): "refused", ("POST", "/api/import"): "refused", ("POST", "/api/screencap"): "settings",
          ("POST", "/api/snapshot"): "redacted", ("POST", "/api/openfolder"): "settings", ("POST", "/api/primary"): "removed",
          ("POST", "/api/call"): "write", ("POST", "/api/missed"): "write", ("POST", "/api/finish"): "write", ("POST", "/api/unblind"): "write",
          ("POST", "/api/wholestudy"): "write", ("GET", "/api/pensieve"): "settings", ("POST", "/api/pensieve_restore"): "settings",
          ("GET", "/api/ident"): "settings", ("GET", "/api/second_look"): "refused", ("POST", "/api/lumos_reject"): "refused",
          ("GET", "/api/albus_marks"): "refused", ("POST", "/api/albus_confirm"): "refused"}
SAFE_ERRORS = (RIO.RecoveryError, RIO.LockTimeout)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _fail(self, e, path, blind):
        """an error reply that cannot leak: refusals of the blind read and storage problems keep their (identifier-free) message; anything
        else during a blind read becomes a generic message with a reference, the detail goes to the server log with digits masked"""
        if isinstance(e, RB.BlindError): return self._send(dict(error=str(e)), code=e.code)
        if isinstance(e, SAFE_ERRORS): return self._send(dict(error=f"{type(e).__name__}: {e}"), code=500)
        if blind:
            ref = secrets.token_hex(4); sys.stderr.write(f"[reviewer] error {ref} on {path}: {type(e).__name__}: {RB.safe_log_text(e)}\n")
            return self._send(dict(error=f"the request could not be completed (reference {ref})"), code=500)
        return self._send(dict(error=f"{type(e).__name__}: {e}"), code=500)
    def _send(self, body, ctype="application/json", code=200):
        if not isinstance(body, (bytes, bytearray, memoryview)): body = json.dumps(body, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)
    def _host_ok(self):
        h = (self.headers.get("Host") or "").split(":")[0]
        return h in ("127.0.0.1", "localhost")
    def do_GET(self):
        if not self._host_ok(): return self._send(dict(error="forbidden host"), code=403)
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}; blind = ROUTES.get(("GET", u.path)) in ("redacted", "refused")
        try:
            if ("GET", u.path) not in ROUTES: return self._send(dict(error="not found"), code=404)
            if u.path == "/api/ident":                                         # 2026-11-25 identity on the image (asked from the app, live)
                sid = q.get("study") or START[0]
                return self._send(viewer_ident(sid if sid in IDS else START[0]))
            if u.path == "/api/pensieve":                                      # 2026-11-25 Pensieve move: state of one study
                pm = _pm(); sid = q.get("study") or START[0]
                return self._send(dict(pm.status(B, sid) if pm else dict(state="on_mac"), study=sid, away=away(sid)))
            if u.path in ("/api/meta", "/api/labels", "/api/vol", "/api/seqmeta") and away(q.get("study") or START[0]):
                sid = q.get("study") or START[0]                             # images on Pensieve: the page brings them back first
                return self._send(dict(in_pensieve=True, study=sid, pensieve=_pm().status(B, sid)))
            if q.get("mode") == "wholestudy" and u.path in ("/api/meta", "/api/labels"):   # Phase 3A.3: no detector output at all
                q["study"] = q.get("study") or START[0]; blind = True
                if u.path == "/api/meta": return self._send(meta(q["study"], q.get("reviewer", ""), "wholestudy"))
                return self._send(np.zeros(study(q["study"]).lab.shape, "<u2").tobytes(order="F"), "application/octet-stream")
            if ROUTES[("GET", u.path)] in ("redacted", "refused"):                    # Phase 3A.2: the server decides the read phase
                q["study"] = q.get("study") or START[0]; st = study(q["study"]); ctx = st.ctx(q.get("reviewer", "")); blind = ctx.blind
                if blind and ROUTES[("GET", u.path)] == "refused": raise RB.BlindError(RB.HIDDEN_MSG)
            if u.path == "/": return self._send(open(os.path.join(HERE, "review_web.html"), "rb").read(), "text/html; charset=utf-8")
            if u.path == "/api/vset":                  # reviewer settings shared by every reviewer window and the app
                f = f"{B}/review/viewer_settings.json"
                return self._send(json.load(open(f)) if os.path.exists(f) else {})
            if u.path == "/api/meta": return self._send(meta(q["study"], q.get("reviewer", ""), q.get("mode", "")))
            if u.path == "/api/vol":
                s = study(q["study"]); return self._send(s.volume(q.get("seq", "swi")).tobytes(order="F"), "application/octet-stream")
            if u.path == "/api/seqmeta":
                s = study(q["study"]); s.volume(q["seq"]); return self._send(s.meta_seq[q["seq"]])
            if u.path == "/api/struct3d": return self._send(study(q["study"]).struct3d(int(q["cand"])))
            if u.path == "/api/second_look": return self._send(second_look(q["study"]))
            if u.path == "/api/albus_marks": return self._send(albus_marks(q["study"]))
            if u.path == "/api/uscore": return self._send(uscore_report(q["study"], int(q["cand"])))   # v5.14-gui screen B (read-only)
            if u.path == "/api/morph3d": return self._send(study(q["study"]).morph3d(int(q["cand"]), float(q.get("margin", 8))))
            if u.path == "/morph3d.js": return self._send(open(os.path.join(HERE, "morph3d_view.js"), "rb").read(), "text/javascript; charset=utf-8")
            if u.path == "/api/labels" and q.get("kind") == "extent":       # 2026-11-28: candidate extent (derived outline, not a decision)
                E_ = study(q["study"]).extent()
                if E_ is None: return self._send(dict(extent=None, reason="the detector's dark map or candidate map is missing"))
                return self._send(RB.remap_labels(E_, ctx).astype("<u2").tobytes(order="F"), "application/octet-stream")
            if u.path == "/api/labels":
                L = study(q["study"]).labels(q.get("reviewer", ""), q.get("mode") == "validation" or SHOW_EXCL)
                return self._send(RB.remap_labels(L, ctx).astype("<u2").tobytes(order="F"), "application/octet-stream")
            self._send(dict(error="not found"), code=404)
        except Exception as e:
            self._fail(e, u.path, blind)
    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-CSS") != "1": return self._send(dict(error="forbidden"), code=403)
        u = urlparse(self.path); blind = True
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if ("POST", u.path) not in ROUTES: return self._send(dict(error="not found"), code=404)
            if u.path == "/api/reviewer": return self._send(reviewers(d.get("name", "")))
            if u.path == "/api/pensieve_restore":                              # bring a moved study back to the Mac (verified copy)
                pm = _pm(); sid = str(d.get("study", ""))
                if sid not in IDS: return self._send(dict(error="unknown study"), code=400)
                if not pm: return self._send(dict(error="the Pensieve module is not installed"), code=500)
                return self._send(pm.start_restore(B, _vault(), sid))
            if u.path == "/api/vset":
                f = f"{B}/review/viewer_settings.json"; os.makedirs(os.path.dirname(f), exist_ok=True)
                cur = json.load(open(f)) if os.path.exists(f) else {}
                cur.update({k: v for k, v in d.items() if isinstance(k, str) and len(k) < 40 and not k.startswith("vmode_")})
                with RIO.project_lock(B, "viewer_settings"): RIO.atomic_write_json(f, cur)
                return self._send(dict(ok=True))
            s = study(d["study"]); rev = (d.get("reviewer") or "").strip()
            if not rev: return self._send(dict(error="Enter the reviewer name first (upper right)."), code=400)
            if ROUTES[("POST", u.path)] == "removed":                          # Phase 3A.3: no reviewer-window primary / reference choice
                raise RB.BlindError("the reference expert / call policy is set by the administrator in the app (Reviewer calls), not from a reviewer window")
            ctx = s.ctx(rev); blind = ctx.blind                                # Phase 3A.2: the read phase comes from the server's journal
            if blind and ROUTES[("POST", u.path)] == "refused": raise RB.BlindError(RB.HIDDEN_MSG)
            jinfo = dict(read_phase=ctx.ph["phase"], ai_visible=not blind,       # recorded with every journaled change of this request
                         ai_released_in_app=ctx.released)                        # the app showed this study's AI results before a blind read
            if u.path == "/api/unblind":
                return self._send(dict(ok=True, read_phase=RB.unblind(B, s.sid, rev)))
            if u.path == "/api/wholestudy":
                if d.get("action") != "complete": raise RB.BlindError("unknown action", 400)
                return self._send(dict(ok=True, whole_study=s.ws_complete(rev)))
            if u.path == "/api/screencap":            # macOS screencapture: the reviewer window (-R) or an area chosen with the mouse (-i)
                if sys.platform != "darwin": return self._send(dict(error="screen capture needs macOS - use Snapshot (image only)"), code=400)
                folder = os.path.abspath(os.path.expanduser(str(d.get("folder") or f"{B}/review/snapshots/{s.sid}").replace("{study}", s.sid))); os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, safe_name(d.get("name", "") or f"{s.sid}_screen.png"))
                b0, e0 = os.path.splitext(path); k = 2
                while os.path.exists(path): path = f"{b0}_{k}{e0}"; k += 1
                if d.get("mode") == "area": cmd = ["screencapture", "-i", "-x", path]
                else: cmd = ["screencapture", "-x", "-R", ",".join(str(int(float(d.get(k, 0)))) for k in ("x", "y", "w", "h")), path]
                subprocess.run(cmd, timeout=120)
                if not os.path.exists(path): return self._send(dict(error="cancelled"))
                return self._send(dict(ok=True, path=path))
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
                    m = dict(d.get("meta") or {}); c = m.get("cur") or [0, 0, 0]; aff = s.can.affine
                    if blind: m["meter"] = "hidden (blind initial read)"
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
            if u.path == "/api/import" and d.get("mode") == "validation":
                return self._send(dict(error="import is switched off during a validation read (it would unblind you)"), code=400)
            if u.path == "/api/import":
                with LOCK, RIO.study_lock(B, s.sid): calls, n = s.import_calls(rev, str(d.get("source", "")), bool(d.get("overwrite")))
                return self._send(dict(ok=True, calls=calls, imported=n, saved=now()))
            if u.path == "/api/primary":
                name = str(d.get("name") or rev).strip()
                pr = primary(s.sid, name)                     # v5.15: = use this reviewer's calls for this study (newest where they did not call)
                with LOCK:
                    CL.set_policy(B, "study", s.sid, dict(mode="reviewer", reviewer=name, fallback="newest"), by=rev or name)
                    CL.materialize(B, s.sid, by=rev or name, rescore=True)
                return self._send(dict(ok=True, primary=pr))
            if u.path == "/api/call":
                d["cand_id"] = ctx.to_true(d.get("cand_id", 0))                   # blinded id -> candidate (unknown id refused)
            if u.path == "/api/call" and int(d.get("cand_id", 0)) >= AUDIT_OFFSET:      # v5.7 excluded-object audit call
                with LOCK, RIO.study_lock(B, s.sid):                     # Phase 3A.1: read-modify-write under the cross-process lock
                    au = s.load_audit(rev); cid = int(d["cand_id"]); cur = au.get(cid, dict(call="", comment=""))
                    if "call" in d:
                        if d["call"] not in CALLS + [""]: return self._send(dict(error="unknown call"), code=400)
                        cur["call"] = d["call"]; cur["time"] = now()
                    if "comment" in d: cur["comment"] = str(d["comment"])[:500]
                    au[cid] = cur
                    if not cur.get("call") and not cur.get("comment"): au.pop(cid)
                    s.save_audit(rev, au, cid, blind_id=ctx.to_blind(cid) if blind else None, **jinfo); calls, _ = s.load_calls(rev); calls.update(au)
                return self._send(dict(ok=True, calls=RB.redact_calls(calls, ctx) if blind else calls, saved=now()))
            if u.path == "/api/call":
                with LOCK, RIO.study_lock(B, s.sid):                     # Phase 3A.1: read-modify-write under the cross-process lock
                    calls, _ = s.load_calls(rev); cid = int(d["cand_id"]); cur = calls.get(cid, dict(call="", comment=""))
                    if "call" in d:
                        if d["call"] not in CALLS + [""]: return self._send(dict(error="unknown call"), code=400)
                        fine = str(d.get("fine") or "")
                        if fine and fine not in FINE.get(d["call"], ()): return self._send(dict(error=f"label {fine} does not belong to the call {d['call']}"), code=400)
                        cur["call"] = d["call"]; cur["time"] = now(); cur["fine"] = fine
                        if d["call"] and isinstance(cur.get("comment"), str):      # an explicit call confirms an inherited call / answers a hint
                            cur["comment"] = re.sub(r"^\[(inherited|old calls|imported)[^\]]*\]\s*", "", cur["comment"])
                    if "comment" in d: cur["comment"] = str(d["comment"])[:500]
                    calls[cid] = cur
                    if not cur.get("call") and not cur.get("comment"): calls.pop(cid)
                    s.save(rev, calls, cid, d.get("action", "call"), None if blind else d.get("meter"),          # the browser's meter value is not trusted
                           blind_id=ctx.to_blind(cid) if blind else None, **jinfo)
                    if d.get("mode") == "validation" or SHOW_EXCL: calls.update(s.load_audit(rev))
                return self._send(dict(ok=True, calls=RB.redact_calls(calls, ctx) if blind else calls, saved=now()))
            if u.path == "/api/albus_confirm":
                with LOCK: r_ = albus_confirm(s.sid, rev, d, **jinfo)
                return self._send(dict(ok=True, confirmations=r_, saved=now()))
            if u.path == "/api/lumos_reject":
                with LOCK: r_ = lumos_reject(s.sid, rev, d, **jinfo)
                return self._send(dict(ok=True, rejects=r_, saved=now()))
            if u.path == "/api/missed":
                wst = s.ws_state(rev); ws = d.get("mode") == "wholestudy" and wst["started"] and not wst["completed"]
                ctxname = "lumos_suggestion" if d.get("source") == "lumos_suggestion" and not blind else ("whole_study" if ws else "candidate_review")
                with LOCK: m = s.missed_edit(rev, str(d.get("action", "")), d, context=ctxname, **jinfo)
                return self._send(dict(ok=True, missed=RB.redact_missed(m, ctx) if (blind or ws) else m, saved=now()))
            if u.path == "/api/finish":
                with LOCK, RIO.study_lock(B, s.sid):                     # Phase 3A.1
                    calls, _ = s.load_calls(rev); s.save(rev, calls, action="finish", **jinfo)
                c = {k: v["call"] for k, v in calls.items() if v.get("call")}
                acc = sorted(k for k, v in c.items() if v == "cSS"); ich = sorted(k for k, v in c.items() if v == "Near ICH")
                # v5.15: this reviewer's OWN score (ID_score_rev_<name>.json), then the shared score of the EFFECTIVE calls
                cmd = [sys.executable, f"{HERE}/score_css.py", s.sid, "--accept-ids", ",".join(map(str, acc)) or "none",
                       "--ich-ids", ",".join(map(str, ich)) or "none", "--reviewed-ids", ",".join(map(str, sorted(c))) or "none",
                       "--tag", f"rev_{slug(rev)}"]
                r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, CSS_BASE=B, PYTHONWARNINGS="ignore"))
                with LOCK: eff = CL.materialize(B, s.sid, by=rev, rescore=True)
                if eff.get("score_ok") is False: r = subprocess.CompletedProcess(cmd, 1, r.stdout, (r.stderr or "") + "\neffective score failed: " + eff.get("score_note", ""))
                xd_, _ = s._excluded(); au_ = s.load_audit(rev) if d.get("read_mode") == "validation" or d.get("final") else {}
                audit = [dict(id=AUDIT_OFFSET + int(e.excl_id), rule=str(e.get("reason", "")).split(":")[0], region=str(e.get("region", "")).replace("ctx-lh-", "").replace("ctx-rh-", ""),
                              call=au_.get(AUDIT_OFFSET + int(e.excl_id), {}).get("call", "")) for _, e in xd_.iterrows()
                         if (AUDIT_OFFSET + int(e.excl_id)) in au_] if len(xd_) else []
                res = dict(ok=r.returncode == 0, audit=audit, text=(r.stdout + ("\n" + r.stderr[-1500:] if r.returncode else "")).strip(),
                           counts={k: sum(v == k for v in c.values()) for k in CALLS}, unread=len(s.df) - len(c),
                           missed=s.missed().to_dict("records"), reader_score=_score_json(score_path(s.sid, rev)),
                           ai_score=None if blind else ai_score(s))
                if d.get("final"):
                    # final save: one record per study (overwritten by a later final save) + the cohort report
                    lp = f"{B}/review/{s.sid}_review_log.csv"; nrev = 0
                    if os.path.exists(lp):
                        lg = pd.read_csv(lp); nrev = int(((lg.action == "revote") & (lg.reviewer == rev)).sum())
                    fin = dict(study=s.sid, reviewer=rev, saved=now(), reviewer_score=res["reader_score"], ai_score=res["ai_score"],
                               n_candidates=int(len(s.df)), n_read=int(len(c)), n_css=int(len(acc)), n_differ=d.get("n_differ", ""),
                               n_missed=int(len(res["missed"])), n_revoted=nrev, meter_visible=d.get("meter_visible", ""), n_inherited_unconfirmed=d.get("n_inherited_unconfirmed", ""),
                               comparison_shown=bool(d.get("comparison_shown")), n_microbleed=int(sum(v == "Microbleed" for v in c.values())),
                               primary=bool(primary(s.sid) == rev), read_mode="validation" if blind else "second look",   # Phase 3A.2: from the server
                               read_phase=ctx.ph["phase"], ai_visible=not blind)
                    if blind: fin["meter_visible"] = 0
                    au = s.load_audit(rev); xd, _ = s._excluded(); why = dict(zip(xd.excl_id, xd.reason)) if len(xd) else {}
                    fin["audit_n_shown"] = len(s.audit_ids(rev)) if d.get("read_mode") == "validation" else 0
                    fin["audit_n_read"] = sum(1 for v in au.values() if v.get("call"))
                    fin["audit_css"] = [dict(excl_id=k - AUDIT_OFFSET, rule=str(why.get(k - AUDIT_OFFSET, "")).split(":")[0])
                                        for k, v in sorted(au.items()) if v.get("call") == "cSS"]
                    with RIO.study_lock(B, s.sid):                       # Phase 3A.1: the final record is journaled, then written atomically
                        RIO.journal_append(B, s.sid, rev, "final", file=os.path.relpath(final_path(s.sid, rev), B), record=fin)
                        RIO.atomic_write_json(final_path(s.sid, rev), fin)

                    _pensieve_update(s.sid)                                       # PENSIEVE: completion is read from the journals

                    import css_report
                    out, n, xl = css_report.build(B); res["final"] = fin; res["report"] = f"{out}.csv{xl}"
                    if blind and len(c) >= len(s.df):                              # Phase 3A.2: every shown candidate called + final save
                        RB.record_completed(B, s.sid, rev, len(s.df), len(c)); res["initial_complete"] = True
                    # 2026-11-26 audit follow-up: the effective calls were rebuilt BEFORE the final record / blind-read completion existed, so
                    # this reviewer did not count yet -> 0 effective calls and a shared score of 0 (17 studies). Rebuild once more now.
                    with LOCK: eff2 = CL.materialize(B, s.sid, by=rev, rescore=True)
                    if eff2.get("score_ok") is False: res["text"] = (res.get("text") or "") + "\neffective score failed: " + eff2.get("score_note", "")
                if blind:                                                           # no AI content, no candidate numbers, no rules
                    res.update(text="saved", ai_score=None, missed=RB.redact_missed(res["missed"], ctx), reader_score=RB.redact_score(res["reader_score"]),
                               audit=[dict(id=ctx.to_blind(a["id"]), call=a["call"]) for a in res["audit"]])
                    if "final" in res: res["final"] = RB.redact_final(res["final"])
                return self._send(res)
            self._send(dict(error="not found"), code=404)
        except Exception as e:
            self._fail(e, u.path, blind)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0].startswith("-"): sys.exit(__doc__)
    IDS = [s for s in a[0].split(",") if s]
    port = int(a[a.index("--port") + 1]) if "--port" in a else 8765
    if "--reviewer" in a: reviewers(a[a.index("--reviewer") + 1])
    if "--groups" in a:
        try: GROUPS.update(json.load(open(a[a.index("--groups") + 1])))
        except Exception as e: print(f"groups file not read: {e}")
    START[0] = a[a.index("--start") + 1] if "--start" in a and a[a.index("--start") + 1] in IDS else IDS[0]
    AUDIT_ON = "--audit" in a; OPEN_READ = "--open" in a; SHOW_EXCL = "--show-excluded" in a
    for sid in IDS:
        for f in (f"{B}/data/{sid}_swi.nii", f"{B}/review/{sid}_candidates.csv", f"{B}/review/{sid}_candidates.nii.gz"):
            if not os.path.exists(f) and not (f.endswith("_swi.nii") and away(sid)):   # moved to Pensieve: restored on open
                sys.exit(f"{sid}: {f} not found - run the detection first")
    for p in range(port, port + 20):
        try: srv = ThreadingHTTPServer(("127.0.0.1", p), H); break
        except OSError: continue
    else: sys.exit(f"no free port between {port} and {port + 19}")
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"cSS reviewer for {', '.join(IDS)}: {url}   (this computer only; Ctrl+C here to stop)", flush=True)
    if SHOW_EXCL: print("SHOW EXCLUDED: every rule-excluded object is listed after the candidates (number 10000 + id, rule shown); its calls are never scored", flush=True)
    if OPEN_READ: print("--open: a second look starts opened; every reviewer's first read of a study stays blind (server-enforced)", flush=True)
    print("shown candidates only (rule-excluded objects hidden)" if not AUDIT_ON else "AUDIT: a 20 % sample of the rule-excluded objects is mixed into validation reads", flush=True)
    RIO.clean_orphan_tmp(f"{B}/review")                                     # Phase 3A.1: temporary files left by a crash (own prefix only)
    if not away(START[0]): study(START[0])
    if "--no-browser" not in a: threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\nstopped; all decisions were saved as they were made")
