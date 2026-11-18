"""Stage 0 read-only volume-gate impact study on phantoms. Inserts small subpial cSS-like patches of controlled volume and
shape into COPIES of the PH3 phantom (study ids VG1..), runs the UNMODIFIED production detector, and maps every
inserted lesion to its fate: shown / excluded (rule) / dropped (generation gate, with measured value) / not generated.
Usage: python volume_gate_sweep.py CSS_BASE SCRIPTS_DIR OUT_DIR"""
import sys, os, shutil, subprocess, json, numpy as np, pandas as pd, nibabel as nib
from scipy import ndimage as ndi
B, S, OUT = sys.argv[1:4]; os.makedirs(OUT, exist_ok=True)
swi = nib.load(f"{B}/data/PH3_swi.nii"); I0 = np.asarray(swi.dataobj, np.float32); vox = np.array(swi.header.get_zooms()[:3], float)
seg = np.asarray(nib.load(f"{B}/work/PH3_t1seg_swispace.nii.gz").dataobj).astype(int)
psd = np.asarray(nib.load(f"{B}/work/PH3_pial_sd.nii.gz").dataobj, np.float32)
truth = np.asarray(nib.load(f"{B}/work/PH3_truth.nii.gz").dataobj) > 0
veins = np.asarray(nib.load(f"{B}/work/PH3_veins.nii.gz").dataobj) > 0
cort = seg >= 1000
# candidate seed sites: subpial cortex, far (>= 14 mm) from phantom lesions/veins and each other, middle 60 % of height
far = ndi.distance_transform_edt(~(truth | veins), sampling=vox) > 10
kk = np.nonzero(cort.any((0, 1)))[0]; zlo, zhi = kk.min() + 0.25 * (kk.max() - kk.min()), kk.min() + 0.8 * (kk.max() - kk.min())
Lh = (seg >= 1000) & (seg < 2000); Rh = seg >= 2000
offmid = np.where(Lh, ndi.distance_transform_edt(~Rh, sampling=vox), ndi.distance_transform_edt(~Lh, sampling=vox)) > 12   # avoid E13/E22 midline zone
OFFMID = os.environ.get('VG_OFFMID', '1') == '1'   # 0 = sites anywhere (run 1 of the audit), 1 = >= 12 mm from the other hemisphere
site = cort & (psd > -0.9) & (psd <= 0) & far & (offmid if OFFMID else True)
site[:, :, :int(zlo)] = False; site[:, :, int(zhi):] = False
rng = np.random.default_rng(7); cand = np.argwhere(site); rng.shuffle(cand)
# designs: (name, kind, size parameter). kind 'disc' = subpial patch radius r (mm) over 2 depth voxels; 'band' = 1-slice-high strip
designs = [("disc_r1.5", "disc", 1.5), ("disc_r2.0", "disc", 2.0), ("disc_r2.5", "disc", 2.5), ("disc_r3.0", "disc", 3.0),
           ("disc_r3.5", "disc", 3.5), ("disc_r4.5", "disc", 4.5), ("disc_r6", "disc", 6.0),
           ("strip_1slice_L8", "strip", (1, 8)), ("strip_1slice_L14", "strip", (1, 14)), ("strip_2slice_L8", "strip", (2, 8)),
           ("strip_2slice_L14", "strip", (2, 14)), ("frag_r4.5", "frag", 4.5)]
REPS = 3                      # each design 3 times at different sites -> 36 lesions in 3 copies (12 per copy, spaced)
g = np.indices(I0.shape).astype(np.float32)
def lesion_mask(c, kind, p):
    d = np.sqrt(sum(((g[a] - c[a]) * vox[a]) ** 2 for a in range(3)))
    band = cort & (psd > -1.3) & (psd <= 0.1)
    if kind == "disc": return band & (d <= p)
    if kind == "frag":
        m = band & (d <= p); holes = ndi.binary_dilation(rng.random(m.shape) < 0.02, iterations=1)   # ~1.5-voxel holes, ~45 % removed
        return m & ~holes
    if kind == "strip":
        nsl, L = p; dz = np.abs(g[2] - c[2]); m = band & (dz < nsl / 2 + 1e-3 if nsl % 2 else (g[2] - c[2] >= 0) & (g[2] - c[2] < nsl))
        return m & (np.sqrt(((g[0] - c[0]) * vox[0]) ** 2 + ((g[1] - c[1]) * vox[1]) ** 2) <= L / 2)
def darken(I, m, f=0.6, blur=0.6):
    w = np.clip(ndi.gaussian_filter(m.astype(np.float32), [blur / v for v in vox]) * 1.6, 0, 1); return I * (1 - f * w)
rows = []; used = []
ci = 0
for rep in range(REPS):
    sid = f"VG{rep + 1}"; I = I0.copy(); lab = np.zeros(I0.shape, np.int16)
    for li, (nm, kind, p) in enumerate(designs, 1):
        while True:
            c = cand[ci]; ci += 1
            if all(np.sqrt((((c - u) * vox) ** 2).sum()) > 12 for u in used): break
        used.append(c); m = lesion_mask(c, kind, p) & (lab == 0)
        lab[m] = li; I = darken(I, m)
        rows.append(dict(study=sid, lesion=li, design=nm, kind=kind, true_vol_mm3=round(float(m.sum() * vox.prod()), 1),
                         true_slices=int(m.any((0, 1)).sum()), vox_i=int(c[0]), vox_j=int(c[1]), vox_k=int(c[2])))
    nib.save(nib.Nifti1Image(I, swi.affine, swi.header), f"{B}/data/{sid}_swi.nii")
    for f in os.listdir(f"{B}/work"):
        if f.startswith("PH3_") and any(f.endswith(x) for x in ("seg_swispace.nii.gz", "t1seg_swispace.nii.gz", "a2009s_swispace.nii.gz")):
            shutil.copy(f"{B}/work/{f}", f"{B}/work/{f.replace('PH3_', sid + '_')}")
    if os.path.exists(f"{B}/synthseg/PH3_seg.nii.gz"): shutil.copy(f"{B}/synthseg/PH3_seg.nii.gz", f"{B}/synthseg/{sid}_seg.nii.gz")
    nib.save(nib.Nifti1Image(lab, swi.affine), f"{OUT}/{sid}_inserted.nii.gz")
    env = dict(os.environ, CSS_V53="1", CSS_ZONE2="1")
    r = subprocess.run([sys.executable, f"{S}/detect_css.py", sid], env=env, capture_output=True, text=True)
    open(f"{OUT}/{sid}_detect.log", "w").write(r.stdout + r.stderr)
    if r.returncode: print(sid, "detect rc", r.returncode, r.stderr[-500:]); sys.exit(1)
df = pd.DataFrame(rows)
def ld(p): return np.asarray(nib.load(p).dataobj).astype(int) if os.path.exists(p) else None
fates = []
for sid, sub in df.groupby("study"):
    ins = ld(f"{OUT}/{sid}_inserted.nii.gz"); cn = ld(f"{B}/review/{sid}_candidates.nii.gz"); ex = ld(f"{B}/review/{sid}_excluded.nii.gz")
    dr = ld(f"{B}/work/{sid}_dropped.nii.gz"); gen = ld(f"{B}/work/{sid}_gen.nii.gz")
    dcsv = pd.read_csv(f"{B}/work/{sid}_dropped.csv") if os.path.exists(f"{B}/work/{sid}_dropped.csv") else pd.DataFrame()
    ecsv = pd.read_csv(f"{B}/review/{sid}_excluded.csv"); ccsv = pd.read_csv(f"{B}/review/{sid}_candidates.csv")
    for r in sub.itertuples():
        m = ins == r.lesion; mm = ndi.binary_dilation(m, iterations=1)
        f = dict(fate="not generated", detail="", measured=np.nan)
        hit = np.unique(cn[mm & (cn > 0)]) if cn is not None else []
        if len(hit):
            f = dict(fate="shown", detail="cand " + ",".join(map(str, hit)), measured=float(ccsv[ccsv.cand_id.isin(hit)].volume_mm3.sum()))
        else:
            he = np.unique(ex[mm & (ex > 0)]) if ex is not None else []
            if len(he):
                e = ecsv[ecsv.iloc[:, 0].isin(he)] if len(ecsv) else ecsv
                f = dict(fate="excluded", detail="; ".join(str(x) for x in e.get("reason", e.iloc[:, 1]).tolist())[:120], measured=float(e.volume_mm3.sum()) if "volume_mm3" in e else np.nan)
            else:
                hd = np.unique(dr[mm & (dr > 0)]) if dr is not None else []
                if len(hd):
                    d = dcsv[dcsv.drop_id.isin(hd)]
                    f = dict(fate="dropped (generation gate)", detail="; ".join(f"{a} {b}" for a, b in zip(d.gate_id, d.measured)), measured=float(d.volume_mm3.max()))
                else:
                    bits = gen[m]
                    why = ("no strong seed" if (bits & 64).any() else "no ridge > strong pct" if (bits & 32).any() else "not dark enough" if not (bits & 16).any() else "no ridge")
                    f = dict(fate="not generated", detail=why, measured=np.nan)
        fates.append(f)
df = pd.concat([df, pd.DataFrame(fates)], axis=1)
df.to_csv(f"{OUT}/volume_gate_sweep.csv", index=False)
print(df.groupby("design").agg(true_vol=("true_vol_mm3", "median"), slices=("true_slices", "median"),
      shown=("fate", lambda s: (s == "shown").sum()), dropped=("fate", lambda s: s.str.startswith("dropped").sum()),
      excluded=("fate", lambda s: (s == "excluded").sum()), notgen=("fate", lambda s: (s == "not generated").sum())).to_string())
print(df[["study", "lesion", "design", "true_vol_mm3", "fate", "detail", "measured"]].to_string(index=False))
