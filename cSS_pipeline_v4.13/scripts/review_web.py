#!/usr/bin/env python3
"""Interactive cSS reviewer in the browser (v5.4). Research software; expert review required.
usage: review_web.py M12[,M13,...] [--port 8765] [--no-browser] [--reviewer "NAME"] [--audit]
Only the detector's SHOWN candidates are listed: objects the exclusion rules removed are never shown (v5.7-E-fix5 default).
  --open    open read: no validation (blind) read - AI meter, AI score, comparison, import and export all available from the start
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
from css_common import base as _base, save_calls, FP, norm_call, LABELS
import call_ledger as CL      # v5.15: every reviewer kept; shared ID_calls.csv / ID_score.json = EFFECTIVE calls (policy, default newest)

B = _base()
CALLS = ["cSS", "Vessel", "Normal", "Artifact", "Unsure", "Near ICH", "Microbleed"]   # v5.7: Microbleed (fine code MB) = not cSS
# v5.17 Quick Add: optional fine label (css_common.LABELS code) recorded WITH a call; it never changes the call's meaning (see label_schema.py)
FINE = {"cSS": ("C",), "Vessel": ("V", "VS", "VC", "VT", "VX", "TV"), "Normal": ("N", "NI", "CA", "SAH", "LN", "HI"), "Artifact": ("A", "AM"),
        "Microbleed": ("MB",), "Unsure": ("U",), "Near ICH": ("H",)}
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
        json.dump(dict(reviewer=set_to.strip(), set=now()), open(p, "w"), indent=1); cur = set_to.strip()
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
    tier = int(f("review_priority_rank", 1)); treason = str(r.get("review_priority_reason", "") or "")
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

    # ---------- v5.7 validation read: a sample of EXCLUDED objects mixed into the list (never scored) ----------
    def _excluded(self):
        if getattr(self, "_aud_xl", None) is None:
            xp, xn = f"{B}/review/{self.sid}_excluded.csv", f"{B}/review/{self.sid}_excluded.nii.gz"
            xd = pd.read_csv(xp) if os.path.exists(xp) else pd.DataFrame()
            if len(xd) and "excl_id" in xd.columns and os.path.exists(xn):
                self._aud_xl = self._grid(xn, order=0).astype(np.int32); self._aud_xd = xd
            else: self._aud_xl = np.zeros(1, np.int32); self._aud_xd = pd.DataFrame()
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

    def apath(self, reviewer): return f"{B}/review/{self.sid}_excluded_audit_{slug(reviewer)}.csv"

    def load_audit(self, reviewer):
        p = self.apath(reviewer)
        if not os.path.exists(p): return {}
        a = pd.read_csv(p); out = {}
        for _, r in a.iterrows():
            out[AUDIT_OFFSET + int(r.excl_id)] = dict(call=norm_call(r.call) if isinstance(r.call, str) else "", comment=r.comment if isinstance(r.get("comment"), str) else "",
                                                     time=r.get("time", "") if isinstance(r.get("time"), str) else "")
        return out

    def save_audit(self, reviewer, calls):
        xd, _ = self._excluded(); why = dict(zip(xd.excl_id, xd.reason)) if len(xd) else {}
        rows = [dict(excl_id=k - AUDIT_OFFSET, call=v.get("call", ""), comment=v.get("comment", ""), reviewer=reviewer, time=v.get("time", ""),
                     rule=str(why.get(k - AUDIT_OFFSET, "")).split(":")[0]) for k, v in sorted(calls.items()) if k >= AUDIT_OFFSET and (v.get("call") or v.get("comment"))]
        pd.DataFrame(rows, columns=["excl_id", "call", "comment", "reviewer", "time", "rule"]).to_csv(self.apath(reviewer), index=False)

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
        if not os.path.exists(p): return {}, ""
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
        self.save(reviewer, mine)
        lp = f"{B}/review/{self.sid}_review_log.csv"; new = not os.path.exists(lp)
        with open(lp, "a") as f:
            if new: f.write("time,reviewer,action,cand_id,call,comment,meter_shown,vox_i,vox_j,vox_k,volume_mm3\n")
            f.write(f'{now()},"{reviewer}",import,,,"{n} calls from {tag}",,,,,\n')
        return mine, n

    def _read_calls(self, p, note):
        c = pd.read_csv(p)
        if not len(c) or not all(k in c.columns for k in FP): return {}, note
        C = self.df[["cand_id"] + FP].to_numpy(float); out = {}; lost = 0
        for _, r in c.iterrows():
            d = np.sqrt(((C[:, 1:4] - r[FP[:3]].to_numpy(float)) ** 2).sum(1))
            dv = np.abs(C[:, 4] - float(r.volume_mm3)) / max(float(r.volume_mm3), 1.0)
            ok = np.where((d <= 2.0) & (dv <= 0.15))[0]
            if not len(ok): lost += 1; continue
            cm = r.get("comment", ""); call = r.get("call", "")
            out[int(C[ok[d[ok].argmin()], 0])] = dict(call=norm_call(call) if isinstance(call, str) else "",
                                                     comment=cm if isinstance(cm, str) else "",
                                                     time=r.get("time") if isinstance(r.get("time"), str) else "",
                                                     fine=r.get("fine_code") if isinstance(r.get("fine_code"), str) else "")
        if lost: note += f" {lost} earlier call(s) match no current candidate (detector re-run) and were left out."
        return out, note.strip()

    def save(self, reviewer, calls, cand_id=None, action="call", ai=None):
        c = self.df.set_index("cand_id")
        rows = [dict(cand_id=k, call=v["call"], comment=v.get("comment", ""), reviewer=reviewer, time=v.get("time", ""),
                     **{f: c.loc[k, f] for f in FP}, fine_code=v.get("fine", "")) for k, v in sorted(calls.items()) if v.get("call") or v.get("comment")]
        # v5.17: calls made on candidates of an EARLIER run (no current candidate matches them) are kept unchanged - they are the human
        # history that candidate lineage carries forward or asks you to confirm; before v5.17 the next save dropped them
        old = pd.read_csv(self.rpath(reviewer)) if os.path.exists(self.rpath(reviewer)) else pd.DataFrame()
        if len(old) and all(k in old.columns for k in FP):
            C = self.df[FP].to_numpy(float); keep = []
            for _, r in old.iterrows():
                dd = np.sqrt(((C[:, :3] - r[FP[:3]].to_numpy(float)) ** 2).sum(1)); dv = np.abs(C[:, 3] - float(r.volume_mm3)) / max(float(r.volume_mm3), 1.0)
                if not ((dd <= 2.0) & (dv <= 0.15)).any(): keep.append(r.to_dict())
            rows += keep
        pd.DataFrame(rows, columns=["cand_id", "call", "comment", "reviewer", "time"] + FP + ["fine_code"]).to_csv(self.rpath(reviewer), index=False)
        primary(self.sid, reviewer, if_missing=True)                              # kept for display / the "use this reviewer" choice
        CL.materialize(B, self.sid, by=reviewer, rescore=False)                  # v5.15: shared ID_calls.csv = effective calls (no re-score per click)
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
# v5.20 display labels from the Percival app (in memory, never written to disk): Standard = accession number, Incognito = code.
# Run on its own (no label map) the reviewer shows the study keys as before.
# (named STUDY_LABELS: 'LABELS' is css_common's fine-label table, used by meta() - v5.23 fix of the v5.20 name clash that broke /api/meta)
try: STUDY_LABELS = json.loads(os.environ.get("CSS_STUDY_LABELS", "") or "{}")
except Exception: STUDY_LABELS = {}
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
    """v5.7: do the FreeSurfer hemisphere labels agree with the image sides? World coordinates (RAS, x+ = patient right):
    (1) the left-labelled tissue must lie at smaller x than the right-labelled tissue; (2) each candidate's centre must lie
    on the side of the mid-point between the two hemisphere centroids that its hemisphere label says."""
    try:
        sp = f"{B}/work/{s.sid}_seg_swispace.nii.gz"
        if not os.path.exists(sp): return dict(n=0, agree=0, bad=False, labels_ok=None)
        seg = s._grid(sp, order=0).astype(np.int32); A = s.can.affine
        L = ((seg >= 1000) & (seg < 2000)) | np.isin(seg, (2, 3)); Rt = (seg >= 2000) | np.isin(seg, (41, 42))
        if L.sum() < 1000 or Rt.sum() < 1000: return dict(n=0, agree=0, bad=False, labels_ok=None)
        wx = lambda m: float((A @ np.r_[np.argwhere(m)[:: 50].mean(0), 1.0])[0])
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
    s = study(sid); calls, note = s.load_calls(reviewer) if reviewer else ({}, "")
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
    up = f"{B}/unified_engine/percival/scores/{sid}.json"                # v5.22 Percival Score of the app's local model (display only, an AI prediction)
    try: percival = json.load(open(up)) if os.path.exists(up) else None
    except Exception: percival = None
    return dict(study=sid, studies=IDS, labels={k: STUDY_LABELS[k] for k in IDS if k in STUDY_LABELS}, percival=percival, groups=GROUPS, shape=list(s.shape), vox=s.vox, cands=cands, calls=calls, mode="validation" if audit else "", open_read=OPEN_READ, note=note, qc=s.qc,
                seqs=[dict(key=k, **{a: b for a, b in s.meta_seq.get(k, dict(label=SEQ_NAMES[k])).items()}) for k in s.avail],
                missing_seqs=[SEQ_NAMES[k] for k in ("flair", "t1", "t2", "phase") if k not in s.avail], ai_score=ai_score(s),
                reader_score=(_score_json(score_path(sid, reviewer)) if calls else None),
                final=load_final(sid, reviewer) if reviewer else None, primary=primary(sid), calls_rule=CL.effective(B, sid)["rule_text"],
                import_sources=s.import_sources(reviewer) if reviewer else [],
                ref=dict(mu=s.mu, sd=s.sd, src=s.ref_src), missed=s.missed().to_dict("records"), reviewers=reviewers(),
                call_names=CALLS, fine_labels={k: [[c, LABELS[c][0]] for c in v] for k, v in FINE.items()}, side_check=side_check(s), snapdir=f"{B}/review/snapshots/{sid}", acq=acq_info(sid))


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
            if u.path == "/api/vset":                  # reviewer settings shared by every reviewer window and the app
                f = f"{B}/review/viewer_settings.json"
                return self._send(json.load(open(f)) if os.path.exists(f) else {})
            if u.path == "/api/meta": return self._send(meta(q.get("study") or START[0], q.get("reviewer", ""), q.get("mode", "")))
            if u.path == "/api/vol":
                s = study(q["study"]); return self._send(s.volume(q.get("seq", "swi")).tobytes(order="F"), "application/octet-stream")
            if u.path == "/api/seqmeta":
                s = study(q["study"]); s.volume(q["seq"]); return self._send(s.meta_seq[q["seq"]])
            if u.path == "/api/struct3d": return self._send(study(q["study"]).struct3d(int(q["cand"])))
            if u.path == "/api/uscore": return self._send(uscore_report(q["study"], int(q["cand"])))   # v5.14-gui screen B (read-only)
            if u.path == "/api/morph3d": return self._send(study(q["study"]).morph3d(int(q["cand"]), float(q.get("margin", 8))))
            if u.path == "/morph3d.js": return self._send(open(os.path.join(HERE, "morph3d_view.js"), "rb").read(), "text/javascript; charset=utf-8")
            if u.path == "/api/labels":
                L = study(q["study"]).labels(q.get("reviewer", ""), q.get("mode") == "validation" or SHOW_EXCL)
                return self._send(L.astype("<u2").tobytes(order="F"), "application/octet-stream")
            self._send(dict(error="not found"), code=404)
        except Exception as e:
            self._send(dict(error=f"{type(e).__name__}: {e}"), code=500)
    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-CSS") != "1": return self._send(dict(error="forbidden"), code=403)
        u = urlparse(self.path)
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if u.path == "/api/reviewer": return self._send(reviewers(d.get("name", "")))
            if u.path == "/api/vset":
                f = f"{B}/review/viewer_settings.json"; os.makedirs(os.path.dirname(f), exist_ok=True)
                cur = json.load(open(f)) if os.path.exists(f) else {}
                cur.update({k: v for k, v in d.items() if isinstance(k, str) and len(k) < 40 and not k.startswith("vmode_")})
                json.dump(cur, open(f + ".tmp", "w"), indent=1); os.replace(f + ".tmp", f); return self._send(dict(ok=True))
            s = study(d["study"]); rev = (d.get("reviewer") or "").strip()
            if not rev: return self._send(dict(error="Enter the reviewer name first (upper right)."), code=400)
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
            if u.path == "/api/import" and d.get("mode") == "validation":
                return self._send(dict(error="import is switched off during a validation read (it would unblind you)"), code=400)
            if u.path == "/api/import":
                with LOCK: calls, n = s.import_calls(rev, str(d.get("source", "")), bool(d.get("overwrite")))
                return self._send(dict(ok=True, calls=calls, imported=n, saved=now()))
            if u.path == "/api/primary":
                name = str(d.get("name") or rev).strip()
                pr = primary(s.sid, name)                     # v5.15: = use this reviewer's calls for this study (newest where they did not call)
                with LOCK:
                    CL.set_policy(B, "study", s.sid, dict(mode="reviewer", reviewer=name, fallback="newest"), by=rev or name)
                    CL.materialize(B, s.sid, by=rev or name, rescore=True)
                return self._send(dict(ok=True, primary=pr))
            if u.path == "/api/call" and int(d.get("cand_id", 0)) >= AUDIT_OFFSET:      # v5.7 excluded-object audit call
                with LOCK:
                    au = s.load_audit(rev); cid = int(d["cand_id"]); cur = au.get(cid, dict(call="", comment=""))
                    if "call" in d:
                        if d["call"] not in CALLS + [""]: return self._send(dict(error="unknown call"), code=400)
                        cur["call"] = d["call"]; cur["time"] = now()
                    if "comment" in d: cur["comment"] = str(d["comment"])[:500]
                    au[cid] = cur
                    if not cur.get("call") and not cur.get("comment"): au.pop(cid)
                    s.save_audit(rev, au); calls, _ = s.load_calls(rev); calls.update(au)
                return self._send(dict(ok=True, calls=calls, saved=now()))
            if u.path == "/api/call":
                with LOCK:
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
                    s.save(rev, calls, cid, d.get("action", "call"), d.get("meter"))
                    if d.get("mode") == "validation" or SHOW_EXCL: calls.update(s.load_audit(rev))
                return self._send(dict(ok=True, calls=calls, saved=now()))
            if u.path == "/api/missed":
                with LOCK: m = s.missed_edit(rev, d["action"], d)
                return self._send(dict(ok=True, missed=m, saved=now()))
            if u.path == "/api/finish":
                calls, _ = s.load_calls(rev); c = {k: v["call"] for k, v in calls.items() if v.get("call")}
                acc = sorted(k for k, v in c.items() if v == "cSS"); ich = sorted(k for k, v in c.items() if v == "Near ICH")
                with LOCK: s.save(rev, calls)
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
                           ai_score=ai_score(s))
                if d.get("final"):
                    # final save: one record per study (overwritten by a later final save) + the cohort report
                    lp = f"{B}/review/{s.sid}_review_log.csv"; nrev = 0
                    if os.path.exists(lp):
                        lg = pd.read_csv(lp); nrev = int(((lg.action == "revote") & (lg.reviewer == rev)).sum())
                    fin = dict(study=s.sid, reviewer=rev, saved=now(), reviewer_score=res["reader_score"], ai_score=res["ai_score"],
                               n_candidates=int(len(s.df)), n_read=int(len(c)), n_css=int(len(acc)), n_differ=d.get("n_differ", ""),
                               n_missed=int(len(res["missed"])), n_revoted=nrev, meter_visible=d.get("meter_visible", ""), n_inherited_unconfirmed=d.get("n_inherited_unconfirmed", ""),
                               comparison_shown=bool(d.get("comparison_shown")), n_microbleed=int(sum(v == "Microbleed" for v in c.values())),
                               primary=bool(primary(s.sid) == rev), read_mode=d.get("read_mode", ""))
                    au = s.load_audit(rev); xd, _ = s._excluded(); why = dict(zip(xd.excl_id, xd.reason)) if len(xd) else {}
                    fin["audit_n_shown"] = len(s.audit_ids(rev)) if d.get("read_mode") == "validation" else 0
                    fin["audit_n_read"] = sum(1 for v in au.values() if v.get("call"))
                    fin["audit_css"] = [dict(excl_id=k - AUDIT_OFFSET, rule=str(why.get(k - AUDIT_OFFSET, "")).split(":")[0])
                                        for k, v in sorted(au.items()) if v.get("call") == "cSS"]
                    json.dump(fin, open(final_path(s.sid, rev), "w"), indent=1)
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
    if "--groups" in a:
        try: GROUPS.update(json.load(open(a[a.index("--groups") + 1])))
        except Exception as e: print(f"groups file not read: {e}")
    START[0] = a[a.index("--start") + 1] if "--start" in a and a[a.index("--start") + 1] in IDS else IDS[0]
    AUDIT_ON = "--audit" in a; OPEN_READ = "--open" in a; SHOW_EXCL = "--show-excluded" in a
    for sid in IDS:
        for f in (f"{B}/data/{sid}_swi.nii", f"{B}/review/{sid}_candidates.csv", f"{B}/review/{sid}_candidates.nii.gz"):
            if not os.path.exists(f): sys.exit(f"{sid}: {f} not found - run the detection first")
    for p in range(port, port + 20):
        try: srv = ThreadingHTTPServer(("127.0.0.1", p), H); break
        except OSError: continue
    else: sys.exit(f"no free port between {port} and {port + 19}")
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"cSS reviewer for {', '.join(IDS)}: {url}   (this computer only; Ctrl+C here to stop)", flush=True)
    if SHOW_EXCL: print("SHOW EXCLUDED: every rule-excluded object is listed after the candidates (number 10000 + id, rule shown); its calls are never scored", flush=True)
    if OPEN_READ: print("OPEN READ: AI meter and AI score visible, no blind validation read", flush=True)
    print("shown candidates only (rule-excluded objects hidden)" if not AUDIT_ON else "AUDIT: a 20 % sample of the rule-excluded objects is mixed into validation reads", flush=True)
    study(START[0])
    if "--no-browser" not in a: threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\nstopped; all decisions were saved as they were made")
