#!/usr/bin/env python3
"""v5.3 acceptance test against the saved reader calls. Research software; expert review required.
usage: v53_compare.py M02,M03,...  [--keep]
For every study it copies data/ID_* and work/ID_* into $CSS_BASE/v53_eval/ (the main project is NOT touched: the
current candidates, calls and scores stay as they are), runs detect_css.py there with CSS_V53=1 and reports, per
reader call, what happened to each candidate of the current list:
  shown     its voxels are in a shown v5.3 candidate (id listed)     excluded  in an excluded object (rule listed)
  dropped   below a generation gate                                 gone      not generated any more (outside the zone)
Summary = the acceptance table of docs/PLAN_v5.3_from_M02-M11.md. Writes review/v53_compare.csv and
review/v53_compare_summary.txt. One study at a time (memory). --keep leaves v53_eval/ in place for freeview.
The reader's calls are the reference; they are not expert lesion labels."""
import sys, os, shutil, subprocess, glob, numpy as np, pandas as pd, nibabel as nib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base, load_calls

ids = [s for s in sys.argv[1].split(",") if s] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else []
if not ids: sys.exit(__doc__)
keep = "--keep" in sys.argv
B = _base(); E = f"{B}/v53_eval"; S = os.path.dirname(os.path.abspath(__file__))
for d in ("data", "work", "review", "results"): os.makedirs(f"{E}/{d}", exist_ok=True)
rows = []; notes = []; allobj = []
FEAT = ["pial_dist_mm", "cortex_frac", "bank_frac", "midline_frac", "skull_frac", "mask_edge_mm", "vent_frac", "infra_frac",
        "basal_frac", "rel_height", "tube_ratio", "tram_frac", "surface_alignment", "axis_normal", "vessel_wm_mm",
        "local_cont_max_mm", "extent_mm", "n_pieces", "darkness_z", "edge_contrast", "region_z", "css_evidence",
        "vein_evidence", "score_v4", "artifact_zone", "cmb_like", "out_frac", "pial_sd_p10_mm", "pial_sd_p90_mm",
        "surface_contact_frac_1mm", "csf_depth_mm", "elongation", "volume_mm3", "plane_dist_mm", "cos_plane", "ext_major_mm", "skullbase_frac", "dual_contact_frac", "zone2_frac", "sylvian_frac"]
def feats(tab, i):
    """features of the v5.3 object this old candidate became (NaN when it was dropped / gone)"""
    if tab is None or not i or i not in tab.index: return {f"v53_{k}": np.nan for k in FEAT}
    r = tab.loc[i]; return {f"v53_{k}": r[k] if k in r.index else np.nan for k in FEAT}
for sid in ids:
    cp, lp = f"{B}/review/{sid}_candidates.csv", f"{B}/review/{sid}_candidates.nii.gz"
    if not (os.path.exists(cp) and os.path.exists(lp)):
        notes.append(f"{sid}: no current candidates - skipped"); continue
    old = pd.read_csv(cp); calls, warn = load_calls(B, sid, old)
    if warn: notes.append(warn)
    for sub in ("data", "work"):
        for f in glob.glob(f"{B}/{sub}/{sid}_*"):
            if os.path.isfile(f): shutil.copy2(f, f"{E}/{sub}/{os.path.basename(f)}")      # copy2 keeps the mtimes
    r = subprocess.run([sys.executable, f"{S}/detect_css.py", sid], env=dict(os.environ, CSS_BASE=E, CSS_V53="1"),
                       capture_output=True, text=True)
    open(f"{E}/review/{sid}_detect.log", "w").write(r.stdout + r.stderr)
    if r.returncode or "v5.3 ACTIVE" not in r.stdout:
        notes.append(f"{sid}: v5.3 detection did not run (exit {r.returncode}; see v53_eval/review/{sid}_detect.log) - "
                     + ("needs T1 anatomy" if "needs T1 anatomy" in r.stdout else "check the log")); continue
    L0 = np.asanyarray(nib.load(lp).dataobj).astype(np.int32)
    L1 = np.asanyarray(nib.load(f"{E}/review/{sid}_candidates.nii.gz").dataobj).astype(np.int32)
    X1 = np.asanyarray(nib.load(f"{E}/review/{sid}_excluded.nii.gz").dataobj).astype(np.int32)
    D1 = np.asanyarray(nib.load(f"{E}/work/{sid}_dropped.nii.gz").dataobj).astype(np.int32)
    new = pd.read_csv(f"{E}/review/{sid}_candidates.csv"); xd = pd.read_csv(f"{E}/review/{sid}_excluded.csv")
    tier = dict(zip(new.cand_id, new.review_priority_rank)) if len(new) else {}
    fnew = new.set_index("cand_id") if len(new) else None; fx = xd.set_index("excl_id") if len(xd) and "excl_id" in xd.columns else None
    for t_, df_ in (("shown", new), ("excluded", xd)):                     # every v5.3 object with its features
        if len(df_): allobj.append(df_.assign(study_id=sid, v53_fate=t_))
    why = dict(zip(xd.excl_id, xd.reason)) if len(xd) else {}
    for _, c in old.iterrows():
        m = L0 == int(c.cand_id); n = int(m.sum())
        if not n: continue
        sh = np.bincount(L1[m]); ex = np.bincount(X1[m]); dr = int((D1[m] > 0).sum())
        n_sh, n_ex = n - int(sh[0]), n - int(ex[0])
        fate = max((("shown", n_sh), ("excluded", n_ex), ("dropped", dr), ("gone", n - n_sh - n_ex - dr)), key=lambda t: t[1])[0]
        if n_sh >= max(3, 0.1 * n): fate = "shown"                 # any real overlap with a shown candidate counts
        nid = int(np.argmax(sh[1:]) + 1) if n_sh else 0; xid = int(np.argmax(ex[1:]) + 1) if n_ex else 0
        rows.append(dict(study_id=sid, cand_id=int(c.cand_id), reader_call=calls.get(int(c.cand_id), ""), hemi=c.hemi,
                         region=c.region, volume_mm3=c.volume_mm3, old_tier=c.get("review_priority_rank", np.nan),
                         fate=fate, shown_frac=round(n_sh / n, 2), new_cand_id=nid if fate == "shown" else "",
                         new_tier=tier.get(nid, "") if fate == "shown" else "",
                         excluded_reason=str(why.get(xid, "")).split(":")[0].split(" (")[0] if fate == "excluded" else "",
                         new_excl_id=xid if fate == "excluded" else "",
                         **feats(fnew if fate == "shown" else fx if fate == "excluded" else None, nid if fate == "shown" else xid)))
    notes.append(f"{sid}: {len(old)} candidates now -> {len(new)} with v5.3 ({len(xd)} excluded)")
    print(notes[-1], flush=True)
    if not keep:
        for sub in ("data", "work"):
            for f in glob.glob(f"{E}/{sub}/{sid}_*"): os.remove(f)
if not rows: sys.exit("\n".join(notes) + "\nnothing to compare")
d = pd.DataFrame(rows); d.to_csv(f"{B}/review/v53_compare.csv", index=False)
if allobj:                                   # all v5.3 objects (shown + excluded) with the reader calls mapped onto them
    A = pd.concat(allobj, ignore_index=True, sort=False)
    sh = d[d.fate == "shown"].groupby(["study_id", "new_cand_id"]).reader_call.agg(lambda s: "+".join(sorted(set(x for x in s if x))))
    ex = d[d.fate == "excluded"].groupby(["study_id", "new_excl_id"]).reader_call.agg(lambda s: "+".join(sorted(set(x for x in s if x))))
    A["reader_calls"] = [sh.get((r.study_id, r.cand_id), "") if r.v53_fate == "shown" else ex.get((r.study_id, r.excl_id), "")
                         for r in A.itertuples()]
    keep = ["study_id", "v53_fate", "cand_id", "excl_id", "reason", "reader_calls", "hemi", "region", "volume_mm3",
            "review_priority_rank"] + FEAT
    A[[c for c in keep if c in A.columns]].to_csv(f"{B}/review/v53_objects.csv", index=False)
out = ["v5.3 acceptance test (reference = the reader's saved calls)", ""] + notes + [""]
out.append(pd.crosstab(d.reader_call.replace("", "(not read)"), d.fate, margins=True).to_string()); out.append("")
css = d[d.reader_call == "cSS"]
if len(css):
    kept = css[css.fate == "shown"]
    out.append(f"cSS calls still shown: {len(kept)} / {len(css)}")
    for _, r in css[css.fate != "shown"].iterrows():
        out.append(f"   LOST {r.study_id}-{r.cand_id} ({r.region}, {r.volume_mm3:.0f} mm3): {r.fate} {r.excluded_reason}")
    n_new = kept.groupby("study_id").new_cand_id.nunique().sum()
    out.append(f"cSS calls shown: {len(kept)} old candidates -> {n_new} v5.3 candidates (fewer = duplicates merged)")
    out.append(f"cSS calls in tier 3: now {(css.old_tier == 3).sum()}, v5.3 {(kept.new_tier == 3).sum()}")
    mixed = d[d.fate == "shown"].groupby(["study_id", "new_cand_id"]).reader_call.agg(lambda s: sorted(set(s)))
    bad = mixed[mixed.apply(lambda s: "cSS" in s and len(s) > 1)]
    out.append(f"v5.3 candidates that join a cSS call with another call: {len(bad)}")
    for (sid, nid), s in bad.items(): out.append(f"   {sid} new #{nid}: {', '.join(x or '(not read)' for x in s)}")
ex = d[d.fate == "excluded"]
if len(ex):
    out.append(""); out.append("Excluded by rule (rows) and reader call (columns):")
    out.append(pd.crosstab(ex.excluded_reason.str.split(":").str[0].str.strip(), ex.reader_call.replace("", "(not read)")).to_string())
out.append("")
for call in ("Artifact", "Normal", "Vessel"):
    a = d[d.reader_call == call]
    if len(a): out.append(f"{call} still shown: {(a.fate == 'shown').sum()} / {len(a)}")
out.append(""); out.append("Patient scores are not recomputed here: read the v5.3 candidates before any score is compared.")
open(f"{B}/review/v53_compare_summary.txt", "w").write("\n".join(out) + "\n")
print("\n".join(out)); print(f"\nwrote {B}/review/v53_compare.csv, v53_objects.csv and v53_compare_summary.txt")
