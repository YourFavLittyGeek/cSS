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
rows = []; notes = []
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
                         excluded_reason=str(why.get(xid, "")).split(":")[0] if fate == "excluded" else ""))
    notes.append(f"{sid}: {len(old)} candidates now -> {len(new)} with v5.3 ({len(xd)} excluded)")
    print(notes[-1], flush=True)
    if not keep:
        for sub in ("data", "work"):
            for f in glob.glob(f"{E}/{sub}/{sid}_*"): os.remove(f)
if not rows: sys.exit("\n".join(notes) + "\nnothing to compare")
d = pd.DataFrame(rows); d.to_csv(f"{B}/review/v53_compare.csv", index=False)
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
for call in ("Artifact", "Normal", "Vein"):
    a = d[d.reader_call == call]
    if len(a): out.append(f"{call} still shown: {(a.fate == 'shown').sum()} / {len(a)}")
out.append(""); out.append("Patient scores are not recomputed here: read the v5.3 candidates before any score is compared.")
open(f"{B}/review/v53_compare_summary.txt", "w").write("\n".join(out) + "\n")
print("\n".join(out)); print(f"\nwrote {B}/review/v53_compare.csv and v53_compare_summary.txt")
