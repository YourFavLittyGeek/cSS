#!/usr/bin/env python3
"""Shape probe: blobs (microbleeds) and 'straight in the sulcus' vs 'tracks into the adjacent cortex'. Research software; expert review required.
usage: shape_probe.py M02,M03,...  [--reads Redo_v53,Blind_v57]
READ-ONLY. For every object (shown + excluded) it measures, on the object and on its DARK SUPPORT (work/ID_gen.nii.gz bit 16 = z < -2.5,
connected to the object, within 6 mm), next to your calls (+ review/adjudication.csv, your final decisions, which replace the reads):
  Blob:     support_over_obj, e1 / e2 / e3 (mm), l_over_m (line >> 1; blob ~1; 3 mm slices: a round blob reads up to ~1.5),
            m_over_s, fill (support volume / ellipsoid volume), esd_mm, plus tram_frac / n_pieces / extent_mm / local_cont_max_mm from the lists
  Sulcus:   bend_ratio (RMS distance from the best straight line / length; straight ~0.04, curved arc ~0.08+ on thin slices),
            depth_p10 / p50 / p90 / depth_range (sulcal depth; crown = 0), crown_frac, deep_frac,
            n_labels / label_spread (how many cortical regions the object touches and how much of its cortex lies outside the main one)
  Rules:    BLOB = compact object (extent <= 12 mm, l_over_m <= a, fill >= f, no tram-track, no dark continuation)
            STRAIGHT = straight in a sulcus without tracking into adjacent cortex (bend_ratio <= b, depth_range <= r, label_spread <= s)
Writes review/shape_probe.csv and shape_probe_summary.txt: distributions by group, the microbleeds you called, the objects closest to each rule,
and a grid per rule with protected cSS flagged (must be 0), shown non-cSS flagged and the margin of the nearest protected cSS."""
import sys, os, itertools, numpy as np, pandas as pd, nibabel as nib
from scipy import ndimage as ndi
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base
import css_shape as cs, probe_common as pc
from css_features import sulcal_depth_map

B = _base(); a = sys.argv[1:]
if not a or a[0].startswith("-"): sys.exit(__doc__)
ids = [s for s in a[0].split(",") if s]
reads = (a[a.index("--reads") + 1] if "--reads" in a else "Redo_v53,Blind_v57").split(",")
CARRY = ["tram_frac", "n_pieces", "extent_mm", "local_cont_max_mm", "tube_ratio", "pial_dist_mm", "cortex_frac", "bank_frac", "elongation", "darkness_z"]
rows = []
for sid in ids:
    need = [f"{B}/data/{sid}_swi.nii", f"{B}/work/{sid}_seg_swispace.nii.gz", f"{B}/work/{sid}_gen.nii.gz", f"{B}/review/{sid}_candidates.csv", f"{B}/review/{sid}_candidates.nii.gz"]
    if any(not os.path.exists(p) for p in need): print(f"{sid}: missing {[os.path.basename(p) for p in need if not os.path.exists(p)]} - skipped"); continue
    vox = np.array(nib.load(need[0]).header.get_zooms()[:3], float); seg = pc.lab(need[1]); gen = np.asanyarray(nib.load(need[2]).dataobj).astype(np.uint8)
    dark = (gen & 16) > 0; cortex = np.where((seg >= 1000) & (seg < 3000), seg, 0).astype(np.int32)
    tissue = (cortex > 0) | np.isin(seg, (2, 3, 41, 42)); depth = sulcal_depth_map(tissue, vox, 5.0)
    pad = np.ceil(8.0 / vox).astype(int) + 2
    objs = []; cand = pd.read_csv(need[3]); objs.append(("shown", cand.set_index("cand_id"), pc.lab(need[4])))
    xp, xl = f"{B}/review/{sid}_excluded.csv", f"{B}/review/{sid}_excluded.nii.gz"
    if os.path.exists(xp) and os.path.exists(xl):
        xd = pd.read_csv(xp)
        if len(xd) and "excl_id" in xd.columns: objs.append(("excluded", xd.set_index("excl_id"), pc.lab(xl)))
    for fate, tab, L in objs:
        cl = pc.object_calls(B, sid, fate, L, reads, cand)
        sl_all = ndi.find_objects(L)
        for oid, r in tab.iterrows():
            if int(oid) > len(sl_all) or sl_all[int(oid) - 1] is None: continue
            sl = tuple(slice(max(s.start - p, 0), s.stop + p) for s, p in zip(sl_all[int(oid) - 1], pad))
            obj = L[sl] == int(oid)
            if obj.sum() < 5: continue
            sup = cs.dark_support(dark[sl], obj, vox, cap_mm=6.0, grow=1)
            bm = cs.blob_measures(sup, obj, vox); coords = np.argwhere(obj)
            _ax = cs.principal(coords, vox)[3][:, 0]; ang = round(float(np.degrees(np.arcsin(min(abs(_ax[2]), 1.0)))), 0)     # angle of the long axis to the axial plane (array axis 2 = S-I)
            rms, br = cs.bend(coords, vox); ds = cs.depth_stats(depth[sl], coords); ts = cs.touch_stats(cortex[sl], obj, vox, 1.5)
            row = dict(study_id=sid, fate=fate, obj_id=int(oid), region=str(r.get("region", "")), volume_mm3=round(float(obj.sum() * vox.prod()), 1),
                       reason=str(r.get("reason", "")).split(":")[0].split(" (")[0] if fate == "excluded" else "", vox_z=round(float(vox[2]), 2),
                       axis_angle_deg=ang, rms_dev_mm=rms, bend_ratio=br, **{k: v for k, v in bm.items()}, **ds, **ts, **pc.summarize(cl.get(int(oid), [])))
            for k in CARRY: row[k] = r.get(k, np.nan)
            rows.append(row)
    print(f"{sid}: {sum(1 for r in rows if r['study_id'] == sid)} objects measured", flush=True)
if not rows: sys.exit("nothing measured")
d = pc.apply_adjudication(pd.DataFrame(rows), B)
d["group"] = np.where(d.css_any == 1, "cSS (final)", np.where(d.non_css == 1, "not cSS (read)", "not read"))
d["microbleed_called"] = d.calls.fillna("").str.contains("Microbleed").astype(int)
d.to_csv(f"{B}/review/shape_probe.csv", index=False)
out = ["Shape probe (research software; expert review required)", f"studies: {', '.join(ids)}   reads: {', '.join(reads)}", "",
       "Objects by fate and group (cSS (final) = PROTECTED when rules are fitted):", pd.crosstab(d.group, d.fate, margins=True).to_string(), ""]
F = ["axis_angle_deg", "extent_mm", "support_over_obj", "l_over_m", "m_over_s", "fill", "bend_ratio", "depth_range", "crown_frac", "deep_frac", "n_labels", "label_spread", "tram_frac", "local_cont_max_mm"]
for f in F:
    out.append(f"{f}: median [10th-90th] by group")
    for g_, g in d.groupby("group"):
        q = pd.to_numeric(g[f], errors="coerce").quantile([.1, .5, .9]).round(2).tolist(); out.append(f"   {g_:<16} n={len(g):<4} {q[1]}  [{q[0]} - {q[2]}]")
    out.append("")
mb = d[d.microbleed_called == 1]
out.append(f"Objects you called MICROBLEED in any read ({len(mb)}): their blob measures (the rule should flag these)")
out.append(mb[["study_id", "fate", "obj_id", "region", "calls", "extent_mm", "l_over_m", "m_over_s", "fill", "support_over_obj", "tram_frac"]].to_string(index=False) if len(mb) else "   none"); out.append("")
prot = d[d.css_any == 1]
out.append("PROTECTED cSS objects that look most like a blob (highest fill, lowest l_over_m; a BLOB rule must stay clear of these):")
out.append(prot[pd.to_numeric(prot.extent_mm, errors="coerce") <= 14].sort_values(["l_over_m", "fill"], ascending=[True, False]).head(8)[
    ["study_id", "obj_id", "region", "extent_mm", "l_over_m", "m_over_s", "fill", "tram_frac", "volume_mm3"]].to_string(index=False)); out.append("")
out.append("PROTECTED cSS objects that look most like a STRAIGHT line in one sulcus (lowest bend, lowest depth range):")
out.append(prot.sort_values(["bend_ratio", "depth_range"]).head(8)[["study_id", "obj_id", "region", "bend_ratio", "depth_range", "label_spread", "n_labels", "e1", "e2"]].to_string(index=False)); out.append("")


def blob(g, a_, f_): return ((pd.to_numeric(g.extent_mm, errors="coerce") <= 12) & (g.l_over_m <= a_) & (g.fill >= f_)
                              & (pd.to_numeric(g.tram_frac, errors="coerce").fillna(0) < 0.2) & (pd.to_numeric(g.local_cont_max_mm, errors="coerce").fillna(0) < 5))


def straight(g, b_, r_, s_): return (g.bend_ratio <= b_) & (g.depth_range <= r_) & (g.label_spread.fillna(0) <= s_)


res = []
for a_, f_ in itertools.product([1.4, 1.6, 1.8, 2.0], [0.3, 0.4, 0.5, 0.6]):
    fl = blob(d, a_, f_); sh = d.fate == "shown"
    res.append(dict(rule="BLOB", p1=a_, p2=f_, p3="", protected=int((fl & (d.css_any == 1)).sum()), of_protected=int((d.css_any == 1).sum()),
                    shown_nonCSS=int((fl & sh & (d.non_css == 1)).sum()), microbleeds=int((fl & (d.microbleed_called == 1)).sum()), of_mb=int(d.microbleed_called.sum()),
                    shown_unread=int((fl & sh & (d.group == "not read")).sum())))
for b_, r_, s_ in itertools.product([0.04, 0.06, 0.08, 0.10], [1.5, 2.5, 3.5, 5.0], [0.2, 0.35, 0.5]):
    fl = straight(d, b_, r_, s_); sh = d.fate == "shown"
    res.append(dict(rule="STRAIGHT", p1=b_, p2=r_, p3=s_, protected=int((fl & (d.css_any == 1)).sum()), of_protected=int((d.css_any == 1).sum()),
                    shown_nonCSS=int((fl & sh & (d.non_css == 1)).sum()), microbleeds=int((fl & (d.microbleed_called == 1)).sum()), of_mb=int(d.microbleed_called.sum()),
                    shown_unread=int((fl & sh & (d.group == "not read")).sum())))
g = pd.DataFrame(res)
out.append("Rule grid (protected must be 0; shown_nonCSS = gain; microbleeds = called microbleeds the rule flags). BLOB: p1 = l_over_m <=, p2 = fill >=; STRAIGHT: p1 = bend <=, p2 = depth_range <=, p3 = label_spread <=")
for nm in ("BLOB", "STRAIGHT"):
    s = g[g.rule == nm]; safe = s[s.protected == 0].sort_values(["shown_nonCSS", "microbleeds"], ascending=False)
    out.append(f"\n{nm}: safe settings (best first)")
    out.append(safe.head(8)[["p1", "p2", "p3", "protected", "shown_nonCSS", "microbleeds", "of_mb", "shown_unread"]].to_string(index=False) if len(safe) else "   none: every setting flags a protected cSS")
out.append("\nNothing was changed. Send review/shape_probe.csv and shape_probe_summary.txt back.")
open(f"{B}/review/shape_probe_summary.txt", "w").write("\n".join(out) + "\n"); print("\n".join(out))
print(f"\nwrote {B}/review/shape_probe.csv and shape_probe_summary.txt")
