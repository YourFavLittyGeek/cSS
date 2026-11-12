#!/usr/bin/env python3
"""3-D structure probe: is the dark structure behind each object a ball, a cylinder or a ribbon, and how does it relate to the cortex?
Research software; expert review required.
usage: struct_probe.py M02,M03,...  [--reads Redo_v53,Blind_v57]  [--cap 20]
READ-ONLY. The detector's object is a thinned ridge; here the WHOLE dark structure it belongs to is regrown (work/ID_dark.nii.gz = dark voxels of the search zone,
26-connected to the object, within --cap mm, default 20) and measured in 3-D, next to your calls (+ review/adjudication.csv, which replaces the reads):
  extents      s1 >= s2 >= s3 (mm, principal axes of the structure), thickness_mm (2 x the 90th percentile of the distance to the structure's edge)
  class        BALL   s1 <= 9 mm and s1 / s3 <= 3                     (microbleed-like)
               TUBE   s1 / s2 >= 2.5 and s2 / s3 <= 2.0               (round cross-section: vessel-like)
               RIBBON s2 / s3 >= 2.0 and s1 >= 9 mm                   (flat: sheet / band)
               OTHER  anything else;  UNRESOLVED when s3 < 1.5 voxels across (3 mm slices: a short tube and a small ball cannot be told apart)
  continues    s1_over_obj (structure length / object length: a vessel runs on beyond the object, cSS stops with the gyrus), struct_over_obj (volume ratio)
  cortex       ctx_frac (share of the structure inside labelled cortex), surf_cos (|cos| of the long axis to the pial normal: ~0 = runs ALONG the surface,
               ~1 = leaves it), depth_p50 (median sulcal depth of the structure)
Rule grids (protected cSS must be 0): BALL_RULE = class BALL and ctx_frac <= c; TUBE_RULE = class TUBE and s1_over_obj >= k and surf_cos >= m.
Writes review/struct_probe.csv and struct_probe_summary.txt. Nothing is changed in the project."""
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
CAP = float(a[a.index("--cap") + 1]) if "--cap" in a else 20.0
BALL_MM, TUBE_R, RIB_R, MIN_VOX_S3 = 9.0, 2.5, 2.0, 1.5


def classify(s1, s2, s3, vmax):
    if s3 < MIN_VOX_S3 * vmax: return "UNRESOLVED"
    if s1 <= BALL_MM and s1 / s3 <= 3.0: return "BALL"
    if s1 / s2 >= TUBE_R and s2 / s3 <= 2.0: return "TUBE"
    if s2 / s3 >= RIB_R and s1 >= BALL_MM: return "RIBBON"
    return "OTHER"


rows = []
for sid in ids:
    need = [f"{B}/data/{sid}_swi.nii", f"{B}/work/{sid}_seg_swispace.nii.gz", f"{B}/work/{sid}_dark.nii.gz", f"{B}/review/{sid}_candidates.csv", f"{B}/review/{sid}_candidates.nii.gz"]
    if any(not os.path.exists(p) for p in need): print(f"{sid}: missing {[os.path.basename(p) for p in need if not os.path.exists(p)]} - skipped"); continue
    vox = np.array(nib.load(need[0]).header.get_zooms()[:3], float); seg = pc.lab(need[1]); dark = np.asanyarray(nib.load(need[2]).dataobj) > 0
    psd_p = f"{B}/work/{sid}_pial_sd.nii.gz"; psd = np.asanyarray(nib.load(psd_p).dataobj).astype(np.float32) if os.path.exists(psd_p) else None
    cortex = (seg >= 1000) & (seg < 3000); tissue = cortex | np.isin(seg, (2, 3, 41, 42)); depth = sulcal_depth_map(tissue, vox, 5.0)
    pad = np.ceil((CAP + 2) / vox).astype(int) + 2
    objs = []; cand = pd.read_csv(need[3]); objs.append(("shown", cand.set_index("cand_id"), pc.lab(need[4])))
    xp, xl = f"{B}/review/{sid}_excluded.csv", f"{B}/review/{sid}_excluded.nii.gz"
    if os.path.exists(xp) and os.path.exists(xl):
        xd = pd.read_csv(xp)
        if len(xd) and "excl_id" in xd.columns: objs.append(("excluded", xd.set_index("excl_id"), pc.lab(xl)))
    for fate, tab, L in objs:
        cl = pc.object_calls(B, sid, fate, L, reads, cand); sl_all = ndi.find_objects(L)
        for oid, r in tab.iterrows():
            if int(oid) > len(sl_all) or sl_all[int(oid) - 1] is None: continue
            sl = tuple(slice(max(s.start - p, 0), s.stop + p) for s, p in zip(sl_all[int(oid) - 1], pad))
            obj = L[sl] == int(oid)
            if obj.sum() < 5: continue
            st = cs.dark_support(dark[sl], obj, vox, cap_mm=CAP, grow=1)
            c = np.argwhere(st); o1 = cs.principal(np.argwhere(obj), vox)[0]; s1, s2, s3, ev = cs.principal(c, vox)
            edt = ndi.distance_transform_edt(ndi.binary_fill_holes(st) | st, sampling=vox); th = 2 * float(np.percentile(edt[st], 90)) if st.any() else np.nan
            ax = ev[:, 0]; cosn = np.nan
            if psd is not None:
                g = np.stack(np.gradient(psd[sl], *vox)); cen = tuple(np.round(c.mean(0)).astype(int).clip(0, np.array(st.shape) - 1)); n = g[(slice(None),) + cen]
                if np.linalg.norm(n) > 1e-6: cosn = abs(float(ax @ (n / np.linalg.norm(n))))
            row = dict(study_id=sid, fate=fate, obj_id=int(oid), region=str(r.get("region", "")), volume_mm3=round(float(obj.sum() * vox.prod()), 1),
                       reason=str(r.get("reason", "")).split(":")[0].split(" (")[0] if fate == "excluded" else "", vox_z=round(float(vox[2]), 2),
                       s1=round(s1, 1), s2=round(s2, 1), s3=round(s3, 1), thickness_mm=round(th, 1), struct_mm3=round(float(st.sum() * vox.prod()), 1),
                       s1_over_obj=round(s1 / max(o1, 1e-6), 2), struct_over_obj=round(float(st.sum() / max(obj.sum(), 1)), 2),
                       ctx_frac=round(float(cortex[sl][st].mean()), 2), surf_cos=round(cosn, 2) if np.isfinite(cosn) else np.nan, depth_p50=round(float(np.median(depth[sl][st])), 1),
                       cls=classify(s1, s2, s3, float(vox.max())), **pc.summarize(cl.get(int(oid), [])))
            rows.append(row)
    print(f"{sid}: {sum(1 for r in rows if r['study_id'] == sid)} objects measured", flush=True)
if not rows: sys.exit("nothing measured")
d = pc.apply_adjudication(pd.DataFrame(rows), B)
d["group"] = np.where(d.css_any == 1, "cSS (final)", np.where(d.non_css == 1, "not cSS (read)", "not read"))
d["microbleed_called"] = d.calls.fillna("").str.contains("Microbleed").astype(int)
d.to_csv(f"{B}/review/struct_probe.csv", index=False)
out = ["3-D structure probe (research software; expert review required)", f"studies: {', '.join(ids)}   reads: {', '.join(reads)}   regrow cap {CAP:g} mm", "",
       "Objects by fate and group (cSS (final) = PROTECTED when rules are fitted):", pd.crosstab(d.group, d.fate, margins=True).to_string(), "",
       "3-D class of the dark structure by group:", pd.crosstab(d.cls, d.group, margins=True).to_string(), "",
       "3-D class of SHOWN objects by group:", pd.crosstab(d[d.fate == "shown"].cls, d[d.fate == "shown"].group, margins=True).to_string(), ""]
for f in ["s1", "s2", "s3", "thickness_mm", "s1_over_obj", "struct_over_obj", "ctx_frac", "surf_cos", "depth_p50"]:
    out.append(f"{f}: median [10th-90th] by group")
    for g_, g in d.groupby("group"):
        q = pd.to_numeric(g[f], errors="coerce").quantile([.1, .5, .9]).round(2).tolist(); out.append(f"   {g_:<16} n={len(g):<4} {q[1]}  [{q[0]} - {q[2]}]")
    out.append("")
mb = d[d.microbleed_called == 1]
out.append(f"Objects you called MICROBLEED in any read ({len(mb)}): their 3-D class (BALL expected)")
out.append(mb[["study_id", "fate", "obj_id", "region", "calls", "s1", "s2", "s3", "cls", "ctx_frac", "s1_over_obj"]].to_string(index=False) if len(mb) else "   none"); out.append("")
prot = d[d.css_any == 1]
out.append("PROTECTED cSS by class: " + str(prot.cls.value_counts().to_dict()))
out.append("PROTECTED cSS classed BALL or TUBE (a rule on that class must stay clear of these):")
out.append(prot[prot.cls.isin(["BALL", "TUBE"])].sort_values("s1")[["study_id", "obj_id", "region", "cls", "s1", "s2", "s3", "ctx_frac", "s1_over_obj", "surf_cos", "volume_mm3"]].head(12).to_string(index=False) or "   none"); out.append("")


def ball(g, c_): return (g.cls == "BALL") & (g.ctx_frac <= c_)
def tube(g, k_, m_): return (g.cls == "TUBE") & (g.s1_over_obj >= k_) & (g.surf_cos.fillna(0) >= m_)


res = []; sh = d.fate == "shown"
for c_ in [0.3, 0.5, 0.7, 0.9, 1.0]:
    fl = ball(d, c_); res.append(dict(rule="BALL", p1=c_, p2="", protected=int((fl & (d.css_any == 1)).sum()), shown_nonCSS=int((fl & sh & (d.non_css == 1)).sum()),
                                      microbleeds=int((fl & (d.microbleed_called == 1)).sum()), shown_unread=int((fl & sh & (d.group == "not read")).sum())))
for k_, m_ in itertools.product([1.5, 2.0, 3.0, 4.0], [0.0, 0.3, 0.5, 0.7]):
    fl = tube(d, k_, m_); res.append(dict(rule="TUBE", p1=k_, p2=m_, protected=int((fl & (d.css_any == 1)).sum()), shown_nonCSS=int((fl & sh & (d.non_css == 1)).sum()),
                                          microbleeds=int((fl & (d.microbleed_called == 1)).sum()), shown_unread=int((fl & sh & (d.group == "not read")).sum())))
g = pd.DataFrame(res); out.append("Rule grids (protected must be 0; shown_nonCSS = gain). BALL: p1 = ctx_frac <=; TUBE: p1 = s1_over_obj >=, p2 = surf_cos >=")
for nm in ("BALL", "TUBE"):
    s = g[g.rule == nm]; safe = s[s.protected == 0].sort_values(["shown_nonCSS", "microbleeds"], ascending=False)
    out.append(f"\n{nm}: safe settings (best first)")
    out.append(safe.head(8)[["p1", "p2", "protected", "shown_nonCSS", "microbleeds", "shown_unread"]].to_string(index=False) if len(safe) else "   none: every setting flags a protected cSS")
out.append("\nNothing was changed. Send review/struct_probe.csv and struct_probe_summary.txt back.")
open(f"{B}/review/struct_probe_summary.txt", "w").write("\n".join(out) + "\n"); print("\n".join(out))
print(f"\nwrote {B}/review/struct_probe.csv and struct_probe_summary.txt")
