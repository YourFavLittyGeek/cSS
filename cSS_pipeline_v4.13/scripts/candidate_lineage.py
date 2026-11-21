#!/usr/bin/env python3
"""candidate_lineage.py - lineage between the candidates of a PREVIOUS run and those of the CURRENT run of one study (v5.17).
Research software. Nothing here changes a candidate, a call or a score; it writes only lineage records.

For every old candidate:   confident   one-to-one, voxel overlap IoU >= CONFIDENT_IOU (or, without label maps, the strict
                                       fingerprint rule of css_common.match_calls: centroid <= 2 voxels, volume within 15 %)
                           possible    some overlap (IoU >= POSSIBLE_IOU) or close (centroid <= POSSIBLE_MM, volume ratio <= 2)
                                       but not confident: split, merge, shift or shape change -> a human must confirm
                           no_match    nothing comparable in the current run (the old object is gone)
For every new candidate:   matched / possible / new (newly detected)
Only CONFIDENT matches may carry an earlier human call forward (call_ledger); possible matches are flagged for re-review.
usage: candidate_lineage.py ID OLD_CANDIDATES.csv OLD_CANDIDATES.nii.gz [--out FILE]   (current = review/ID_candidates.*)"""
import json, os, sys, time
import numpy as np
import pandas as pd

SCHEMA = "css-lineage/1.0"
CONFIDENT_IOU = 0.5
POSSIBLE_IOU = 0.1
POSSIBLE_MM = 6.0
FP = ["vox_i", "vox_j", "vox_k", "volume_mm3"]
MEASURES = ["score_v4", "volume_mm3", "darkness_z", "tube_ratio", "pial_dist_mm", "review_tier", "hemi", "region"]


def _uid(sid, r): return f"{sid}:{int(r['vox_i'])}:{int(r['vox_j'])}:{int(r['vox_k'])}:{float(r['volume_mm3']):g}"


def _labels(path):
    if not path or not os.path.exists(path): return None, None
    import nibabel as nib
    im = nib.load(path); return np.asarray(im.dataobj).astype(np.int32), im


def compute(sid, old_csv, old_nii, new_csv, new_nii, run_old="", run_new=""):
    old = pd.read_csv(old_csv) if os.path.exists(old_csv) else pd.DataFrame(columns=["cand_id"] + FP)
    new = pd.read_csv(new_csv) if os.path.exists(new_csv) else pd.DataFrame(columns=["cand_id"] + FP)
    Lo, io = _labels(old_nii); Ln, inn = _labels(new_nii)
    use_vox = Lo is not None and Ln is not None and Lo.shape == Ln.shape and np.allclose(io.affine, inn.affine, atol=1e-3)
    vox = np.array(inn.header.get_zooms()[:3], float) if inn is not None else np.ones(3)
    pairs = {}                                                      # (old id, new id) -> dict(iou, dist_mm, vol_ratio)
    if use_vox:
        both = (Lo > 0) & (Ln > 0)
        a, b = Lo[both], Ln[both]
        inter = pd.Series(1, index=pd.MultiIndex.from_arrays([a, b])).groupby(level=[0, 1]).sum() if both.any() else pd.Series(dtype=int)
        so = pd.Series(Lo[Lo > 0]).value_counts(); sn = pd.Series(Ln[Ln > 0]).value_counts()
        for (i, j), n in inter.items():
            pairs[(int(i), int(j))] = dict(iou=round(float(n / (so[i] + sn[j] - n)), 4))
    O = old.set_index("cand_id") if len(old) else None; N = new.set_index("cand_id") if len(new) else None
    if O is not None and N is not None and all(c in old.columns for c in FP) and all(c in new.columns for c in FP):
        for i, ro in O.iterrows():
            po = ro[FP[:3]].to_numpy(float)
            for j, rn in N.iterrows():
                d = float(np.sqrt((((rn[FP[:3]].to_numpy(float) - po) * vox) ** 2).sum()))
                vr = max(float(ro.volume_mm3), float(rn.volume_mm3)) / max(min(float(ro.volume_mm3), float(rn.volume_mm3)), 1e-6)
                if d <= POSSIBLE_MM or (int(i), int(j)) in pairs:
                    e = pairs.setdefault((int(i), int(j)), dict(iou=0.0)); e.update(dist_mm=round(d, 2), vol_ratio=round(vr, 3),
                                                                                 fp_match=bool(d <= 2.0 * float(vox.max()) and abs(float(rn.volume_mm3) - float(ro.volume_mm3)) / max(float(ro.volume_mm3), 1) <= 0.15))
    by_old, by_new = {}, {}
    for (i, j), e in pairs.items(): by_old.setdefault(i, []).append((j, e)); by_new.setdefault(j, []).append((i, e))
    def best(lst): return max(lst, key=lambda x: (x[1].get("iou", 0), -x[1].get("dist_mm", 99)))
    old_rows, new_status = [], {}
    for i in ([int(x) for x in old.cand_id] if len(old) else []):
        cand = by_old.get(i, [])
        st, tgt, why = "no_match", None, "nothing comparable in the current run"
        if cand:
            j, e = best(cand); back = best(by_new.get(j, [])) if by_new.get(j) else (None, {})
            mutual = back[0] == i
            # a split (the old object overlaps another current candidate too) or a merge (the current candidate overlaps another old one)
            # is NEVER confident, however large the best overlap is
            others_new = [x for x in cand if x[0] != j and x[1].get("iou", 0) >= POSSIBLE_IOU]
            others_old = [x for x in by_new.get(j, []) if x[0] != i and x[1].get("iou", 0) >= POSSIBLE_IOU]
            clean = not others_new and not others_old
            conf = clean and mutual and ((use_vox and e.get("iou", 0) >= CONFIDENT_IOU) or (not use_vox and e.get("fp_match")))
            near = e.get("iou", 0) >= POSSIBLE_IOU or (e.get("dist_mm", 99) <= POSSIBLE_MM and e.get("vol_ratio", 99) <= 2.0)
            if conf: st, tgt, why = "confident", j, f"one-to-one, IoU {e.get('iou', 0):.2f}" if use_vox else "fingerprint (centroid <= 2 voxels, volume within 15 %)"
            elif near:
                st, tgt = "possible", j
                n_new = len([x for x in cand if x[1].get("iou", 0) >= POSSIBLE_IOU]); n_old = len([x for x in by_new.get(j, []) if x[1].get("iou", 0) >= POSSIBLE_IOU])
                why = ("split into several current candidates" if n_new > 1 else "merged with another earlier candidate" if n_old > 1 else
                       f"overlap IoU {e.get('iou', 0):.2f}" + (f", centroid {e.get('dist_mm')} mm, volume x{e.get('vol_ratio')}" if "dist_mm" in e else "")) + " - confirm"
        r = O.loc[i] if O is not None else {}
        rec = dict(old_cand_id=i, old_uid=_uid(sid, r) if O is not None and all(k in r for k in FP) else "", status=st, new_cand_id=tgt, why=why,
                   iou=(pairs.get((i, tgt)) or {}).get("iou") if tgt is not None else None, dist_mm=(pairs.get((i, tgt)) or {}).get("dist_mm") if tgt is not None else None,
                   others=[dict(new_cand_id=j, **e) for j, e in cand if j != tgt][:5],
                   old=({k: (None if pd.isna(r.get(k)) else (r.get(k).item() if hasattr(r.get(k), "item") else r.get(k))) for k in MEASURES if k in r} if O is not None else {}))
        if tgt is not None and N is not None and tgt in N.index:
            rn = N.loc[tgt]; rec["new"] = {k: (None if pd.isna(rn.get(k)) else (rn.get(k).item() if hasattr(rn.get(k), "item") else rn.get(k))) for k in MEASURES if k in rn}
        old_rows.append(rec)
        if tgt is not None: new_status[tgt] = "matched" if st == "confident" else new_status.get(tgt, "possible")
    for j, lst in by_new.items():                                   # a current candidate that overlaps / is close to an old one is not "new"
        if new_status.get(j) != "matched" and any(e.get("iou", 0) >= POSSIBLE_IOU or (e.get("dist_mm", 99) <= POSSIBLE_MM and e.get("vol_ratio", 99) <= 2.0) for _, e in lst):
            new_status[j] = "possible"
    new_rows = [dict(new_cand_id=int(j), status=new_status.get(int(j), "new"), new_uid=_uid(sid, N.loc[int(j)]) if all(k in new.columns for k in FP) else "")
                for j in (new.cand_id if len(new) else [])]
    summ = {k: sum(1 for r in old_rows if r["status"] == k) for k in ("confident", "possible", "no_match")}
    summ["new"] = sum(1 for r in new_rows if r["status"] == "new"); summ.update(n_old=len(old_rows), n_new=len(new_rows))
    return dict(schema=SCHEMA, study=sid, created=time.strftime("%Y-%m-%d %H:%M:%S"), run_old=run_old, run_new=run_new, method="voxel overlap" if use_vox else "fingerprint",
                thresholds=dict(confident_iou=CONFIDENT_IOU, possible_iou=POSSIBLE_IOU, possible_mm=POSSIBLE_MM), summary=summ, old=old_rows, new=new_rows)


def after_run(base, sid, run_id):
    """lineage between the parent run's archived candidates and the current ones, written to runs/ID/RUN/lineage.json and
    review/ID_lineage.json (the latter = the active comparison the call ledger reads). Returns the record or None."""
    rdir = os.path.join(base, "runs", sid, run_id)
    try:
        with open(os.path.join(rdir, "manifest.json")) as f: m = json.load(f)
    except Exception: return None
    par = m.get("parent")
    if not par: return None
    pf = os.path.join(base, "runs", sid, par, "files", "review")
    oc, on = os.path.join(pf, f"{sid}_candidates.csv"), os.path.join(pf, f"{sid}_candidates.nii.gz")
    if not os.path.exists(oc): return None
    L = compute(sid, oc, on, os.path.join(base, "review", f"{sid}_candidates.csv"), os.path.join(base, "review", f"{sid}_candidates.nii.gz"), par, run_id)
    for p in (os.path.join(rdir, "lineage.json"), os.path.join(base, "review", f"{sid}_lineage.json")):
        with open(p + ".tmp", "w") as f: json.dump(L, f, indent=1, default=str)
        os.replace(p + ".tmp", p)
    return L


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 3: sys.exit(__doc__)
    B = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project"))
    L = compute(a[0], a[1], a[2], f"{B}/review/{a[0]}_candidates.csv", f"{B}/review/{a[0]}_candidates.nii.gz")
    out = a[a.index("--out") + 1] if "--out" in a else None
    txt = json.dumps(L, indent=1, default=str)
    if out:
        with open(out, "w") as f: f.write(txt)
    print(json.dumps(L["summary"]))
