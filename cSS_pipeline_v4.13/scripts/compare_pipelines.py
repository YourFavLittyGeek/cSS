#!/usr/bin/env python3
"""Compare two detections at object level. Research software; expert review required.
usage: compare_pipelines.py A B M02,M03,...  [--reads Redo_v53,Blind_v57]
A and B are "main" (the project itself) or the name of an experiment made by run_experiment.py (or a folder path holding review/ and work/).
READ-ONLY. Every object of A (shown candidate, excluded object, gate-dropped object) is followed into B by voxel overlap and gets its B fate:
  same        shown in A and shown in B        lost      shown in A, excluded / dropped / absent in B   (with the B rule)
  gained      excluded / dropped in A, shown in B                     only_B   a B object that overlaps no A object (soft-gate objects, other merges)
Your calls (the reads of the PROJECT, plus review/adjudication.csv, which replaces them) are attached to the A objects, so the report says how many
objects you called cSS were LOST or GAINED, and how many non-cSS shown objects went away or appeared, per study and per rule.
Writes review/compare_pipelines_<A>_vs_<B>.csv and ..._summary.txt in the project."""
import sys, os, numpy as np, pandas as pd, nibabel as nib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base
import probe_common as pc

P = _base(); a = sys.argv[1:]
if len(a) < 3 or a[0].startswith("-"): sys.exit(__doc__)
nameA, nameB, ids = a[0], a[1], [s for s in a[2].split(",") if s]
reads = (a[a.index("--reads") + 1] if "--reads" in a else "Redo_v53,Blind_v57").split(",")


def root(n):
    if n == "main": return P
    if os.path.isdir(f"{P}/experiments/{n}"): return f"{P}/experiments/{n}"
    if os.path.isdir(n): return n
    sys.exit(f"{n}: not 'main', not an experiment in {P}/experiments and not a folder")


RA, RB = root(nameA), root(nameB)


def load(R, sid):
    """-> dict(shown=(df, labels), excluded=(df, labels), dropped=(df, labels)) or None"""
    out = {}
    for fate, csv, nii, key in (("shown", f"{R}/review/{sid}_candidates.csv", f"{R}/review/{sid}_candidates.nii.gz", "cand_id"),
                                ("excluded", f"{R}/review/{sid}_excluded.csv", f"{R}/review/{sid}_excluded.nii.gz", "excl_id"),
                                ("dropped", f"{R}/work/{sid}_dropped.csv", f"{R}/work/{sid}_dropped.nii.gz", "drop_id")):
        if not (os.path.exists(csv) and os.path.exists(nii)): out[fate] = (pd.DataFrame(columns=[key]), None, key); continue
        out[fate] = (pd.read_csv(csv), pc.lab(nii), key)
    return out if out["shown"][1] is not None else None


def follow(obj_vox, other):
    """fate and id of the object of `other` that overlaps obj_vox most: (fate, id, overlap fraction, rule-or-gate text)"""
    n = len(obj_vox[0]); best = ("gone", 0, 0.0, "")
    for fate in ("shown", "excluded", "dropped"):
        df, L, key = other[fate]
        if L is None: continue
        v = L[obj_vox]; v = v[v > 0]
        if not len(v): continue
        u, c = np.unique(v, return_counts=True); k = int(np.argmax(c)); frac = float(c[k] / n)
        if c[k] >= max(3, 0.1 * n) and frac > best[2]:
            row = df[df[key] == u[k]]
            why = ""
            if len(row): why = str(row.iloc[0].get("reason", "") or row.iloc[0].get("gate_id", "") or "").split(":")[0].split(" (")[0]
            best = (fate, int(u[k]), round(frac, 2), why)
    return best


rows, notes = [], []
for sid in ids:
    A, Bm = load(RA, sid), load(RB, sid)
    if A is None or Bm is None: notes.append(f"{sid}: missing detection in {nameA if A is None else nameB}"); continue
    cand = A["shown"][0]; calls = {}
    bsh = Bm["shown"][0]
    for fate in ("shown", "excluded", "dropped"):
        df, L, key = A[fate]
        if L is None or not len(df): continue
        cl = pc.object_calls(P, sid, fate, L, reads, cand if fate == "shown" else None) if fate != "dropped" else {}
        for oid in df[key]:
            idx = np.nonzero(L == int(oid))
            if not len(idx[0]): continue
            fb = follow(idx, Bm); s = pc.summarize(cl.get(int(oid), []))
            arow = df[df[key] == oid].iloc[0]
            brow = bsh[bsh["cand_id"] == fb[1]].iloc[0] if fb[0] == "shown" and len(bsh[bsh["cand_id"] == fb[1]]) else None
            rows.append(dict(study_id=sid, A_fate=fate, A_id=int(oid),
                             A_rule=str(arow.get("reason", "") or "").split(":")[0].split(" (")[0] if fate != "shown" else "",
                             A_gate=str(arow.get("gate_id", "")) if fate == "dropped" else "",
                             B_fate=fb[0], B_id=fb[1], B_overlap=fb[2], B_rule=fb[3] if fb[0] != "shown" else "",
                             B_soft_gate_fail=str(brow.get("soft_gate_fail", "")) if brow is not None and pd.notna(brow.get("soft_gate_fail", "")) else "", **s))
    # B objects that overlap no A object
    for fate in ("shown",):
        df, L, key = Bm[fate]
        if L is None or not len(df): continue
        for oid in df[key]:
            idx = np.nonzero(L == int(oid))
            if not len(idx[0]): continue
            fa = follow(idx, A)
            if fa[0] == "gone":
                r = df[df[key] == oid].iloc[0]
                rows.append(dict(study_id=sid, A_fate="", A_id=0, A_rule="", A_gate="", B_soft_gate_fail=str(r.get("soft_gate_fail", "") if pd.notna(r.get("soft_gate_fail", "")) else ""), B_fate="shown", B_id=int(oid), B_overlap=0.0, B_rule="", calls="", n_calls=0, n_css=0,
                                 css_any=0, css_all=0, non_css=0, only_B=1))
if not rows: sys.exit("\n".join(notes) + "\nnothing to compare")
d = pc.apply_adjudication(pd.DataFrame(rows), P)
d["only_B"] = d.get("only_B", 0); d["only_B"] = d["only_B"].fillna(0).astype(int)
d["transition"] = np.where(d.only_B == 1, "only_B",
                  np.where((d.A_fate == "shown") & (d.B_fate == "shown"), "same",
                  np.where((d.A_fate == "shown"), "lost", np.where((d.B_fate == "shown"), "gained", "still_out"))))
d["group"] = np.where(d.css_any == 1, "cSS (final)", np.where(d.non_css == 1, "not cSS (read)", "not read"))
tag = f"{nameA}_vs_{nameB}"; d.to_csv(f"{P}/review/compare_pipelines_{tag}.csv", index=False)
out = [f"Pipeline comparison  A = {nameA}   B = {nameB}  (research software; expert review required)", f"studies: {', '.join(ids)}", *notes, "",
       "Objects of A by transition to B (rows) and your call group (columns):", pd.crosstab(d.transition, d.group, margins=True).to_string(), ""]
lost = d[(d.transition == "lost") & (d.css_any == 1)]; gained = d[(d.transition == "gained") & (d.css_any == 1)]
out.append(f"objects you called cSS LOST in B: {len(lost)}" + ("" if not len(lost) else "   <-- check these first"))
if len(lost): out.append(lost[["study_id", "A_id", "B_fate", "B_rule", "calls"]].to_string(index=False))
out.append(f"objects you called cSS GAINED in B (were out in A): {len(gained)}")
if len(gained): out.append(gained[["study_id", "A_id", "A_fate", "A_rule", "calls"]].to_string(index=False))
out += ["", "shown non-cSS objects of A that B removes, by B rule:"]
rm = d[(d.transition == "lost") & (d.non_css == 1)]
out.append(rm.groupby(rm.B_rule.replace("", "(gone)")).size().rename("n").to_string() if len(rm) else "   none")
out.append(f"\nB-only shown objects (no A counterpart at all): {int((d.only_B == 1).sum())}")
_g = d[(d.transition == "gained") & (d.A_fate == "dropped")]
out.append(f"gate-dropped in A, shown in B (soft gates): {len(_g)}" + ("   by gate: " + str(_g.B_soft_gate_fail.replace("", "none").value_counts().to_dict()) if len(_g) else ""))
out.append(f"shown objects: A {int((d.A_fate == 'shown').sum())} -> B {int((d.B_fate == 'shown').sum())}  (B counts objects of A that are shown in B plus the B-only objects)")
out += ["", "per study (A shown -> B shown; lost / gained cSS; lost / only_B non-cSS):"]
for sid, g in d.groupby("study_id"):
    out.append(f"   {sid}: {int((g.A_fate == 'shown').sum())} -> {int((g.B_fate == 'shown').sum())};  cSS lost {int(((g.transition == 'lost') & (g.css_any == 1)).sum())} gained {int(((g.transition == 'gained') & (g.css_any == 1)).sum())};"
               f"  non-cSS lost {int(((g.transition == 'lost') & (g.non_css == 1)).sum())}, only_B {int((g.only_B == 1).sum())}")
out.append("\nNothing was changed. Send the csv and this summary.")
open(f"{P}/review/compare_pipelines_{tag}_summary.txt", "w").write("\n".join(out) + "\n"); print("\n".join(out))
print(f"\nwrote {P}/review/compare_pipelines_{tag}.csv and _summary.txt")
