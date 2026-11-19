"""check_core_decompose.py - independent tests of unified_score/core_decompose.py (EXPERIMENTAL dark-core import).
Own small generator (seeds 9001+, shapes not used in v5.13 development or held-out sets). Phantoms test mechanics only;
they are not validation. Mechanical tests use a stated high-contrast condition (deposit median c >= ~7 noise
units after blur, blur 0.4 mm); the low-contrast regime is MEASURED and reported, not asserted (section 9). Known limits are reported as KNOWN-LIMIT lines and do not fail the run (they are documented
behaviour of the imported code, which this stage must not change).
usage: python tests/check_core_decompose.py   (exit 1 on any FAIL)"""
import os, sys, hashlib, re
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(H), "unified_score", "uscore"))
import numpy as np
from scipy import ndimage as ndi
import core_decompose as cd

FAILS = []; LIMITS = []
def check(name, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {info}"); (None if ok else FAILS.append(name))
def limit(name, info): print(f"KNOWN-LIMIT  {name}  {info}"); LIMITS.append(name)

def grid(shape, vox): return np.stack(np.meshgrid(*[np.arange(n) * v for n, v in zip(shape, vox)], indexing="ij"), -1)

def render(truth_list, shape, vox, seed, sd=5.0, mu=100.0, blur_mm=0.8):
    """truth_list: [(mask, contrast_in_sd)]; image = background + dark deposits blurred (blooming), + noise."""
    rng = np.random.default_rng(seed); dep = np.zeros(shape)
    for m, k in truth_list: dep = np.maximum(dep, m * k * sd * 3.0)
    dep = ndi.gaussian_filter(dep, [blur_mm / v for v in vox])
    return mu - dep + rng.normal(0, sd, shape)

def candidate_from(img, truth_any, vox, mu=100.0, sd=5.0, z=2.0):
    """bloomed candidate: dark voxels (z SD) connected to the truth, within 3 mm of it (like a detector mask)."""
    near = ndi.distance_transform_edt(~truth_any, sampling=vox) <= 3.0
    dark = ((mu - img) / sd >= z) & near
    lab, _ = ndi.label(dark, cd.S26); keep = np.unique(lab[truth_any & (lab > 0)])
    return np.isin(lab, keep[keep > 0])

def recall(core, truth): return float((core & truth).sum() / max(truth.sum(), 1))

vox = np.array([0.5, 0.5, 1.0]); shape = (60, 60, 30); G = grid(shape, vox); X, Y, Z = G[..., 0], G[..., 1], G[..., 2]
c0 = np.array(shape) * vox / 2

# 0 provenance: verbatim function text
src = open(cd.__file__).read()
body = src.split("# ---- verbatim copy of css_morph3d_v2.decompose (do not edit; see provenance) ----\n")[1].split("# ---- end of verbatim copy ----")[0]
fh = re.search(r"function sha256\s+([0-9a-f]{64})", src).group(1)
check("0 verbatim copy matches recorded function sha256", hashlib.sha256(body.encode()).hexdigest() == fh)
check("0 module imports only numpy / scipy", set(re.findall(r"^(?:import|from) (\w+)", src, re.M)) <= {"numpy", "scipy"})

# 1 flat band (sheet, 1 mm thick), strong contrast, blooming
band = (np.abs(X - c0[0]) <= 0.5) & (np.abs(Y - c0[1]) <= 8) & (np.abs(Z - c0[2]) <= 5)
img = render([(band, 3.0)], shape, vox, 9001, blur_mm=0.4); cand = candidate_from(img, band, vox)
r = cd.decompose_experimental(cand, img, vox)
check("1 band: status ok and labelled experimental", r["status"] == "ok" and r["label"] == "experimental")
check("1 band: core smaller than bloomed candidate", r["core"].sum() < cand.sum(), f"core {r['core'].sum()} cand {cand.sum()}")
check("1 band: core recalls the deposit", recall(r["core"], band) >= 0.8, f"recall {recall(r['core'], band):.2f}")
check("1 band: support = candidate minus core", np.array_equal(r["support"], cand & ~r["core"]))
check("1 band: core within 1 voxel of candidate", not (r["core"] & ~ndi.binary_dilation(cand, cd.S26)).any(),
      f"outside candidate {r['core_outside_candidate']}")
bloom = cand & ~band; check("1 band: some blooming moved to support", (r["support"] & bloom).sum() > 0,
                            f"bloom kept in core {(r['core'] & bloom).sum() / max(bloom.sum(), 1):.2f}")

# 2 thin structure (one-voxel tube in plane, 0.5 mm)
tube = (np.abs(X - c0[0]) <= 0.25) & (np.abs(Z - c0[2]) <= 0.5) & (np.abs(Y - c0[1]) <= 10)
img = render([(tube, 5.0)], shape, vox, 9002, blur_mm=0.4); cand = candidate_from(img, tube, vox)
r = cd.decompose_experimental(cand, img, vox)
check("2 thin: core found", r["status"] == "ok", f"core {r['core'].sum()} vox")
check("2 thin: core recalls the thin deposit", recall(r["core"], tube) >= 0.8, f"recall {recall(r['core'], tube):.2f}")
d = ndi.distance_transform_edt(~tube, sampling=vox)[r["core"]]
check("2 thin: core stays near the deposit (median <= 1 mm)", np.median(d) <= 1.0, f"median {np.median(d):.2f} mm")

# 3 curved structure (arc of a 10 mm circle in the x-y plane, 1 mm thick, 4 mm high)
rr = np.hypot(X - c0[0], Y - c0[1] + 4); ang = np.arctan2(Y - c0[1] + 4, X - c0[0])
arc = (np.abs(rr - 10) <= 0.5) & (ang > 0.3) & (ang < 2.8) & (np.abs(Z - c0[2]) <= 2)
img = render([(arc, 3.0)], shape, vox, 9003, blur_mm=0.4); cand = candidate_from(img, arc, vox)
r = cd.decompose_experimental(cand, img, vox)
check("3 curved: core recalls the arc", recall(r["core"], arc) >= 0.8, f"recall {recall(r['core'], arc):.2f}")
cl, ncl = ndi.label(r["core"], cd.S26)
big = np.bincount(cl.ravel())[1:].max() / max(r["core"].sum(), 1) if ncl else 0
print(f"INFO  3 curved: core in {ncl} pieces, largest holds {big:.2f} of core voxels")
if ncl > 1: limit("3 core fragments (per-voxel threshold on noisy contrast)", f"{ncl} pieces; core connectivity / piece counts are not reliable")

# 4 adjacent bands: equal contrast, then strong + weak (tram-track-like), 2 mm apart
b1 = (np.abs(X - (c0[0] - 1.0)) <= 0.25) & (np.abs(Y - c0[1]) <= 8) & (np.abs(Z - c0[2]) <= 4)
b2 = (np.abs(X - (c0[0] + 1.0)) <= 0.25) & (np.abs(Y - c0[1]) <= 8) & (np.abs(Z - c0[2]) <= 4)
img = render([(b1, 4.0), (b2, 4.0)], shape, vox, 9004, blur_mm=0.4); cand = candidate_from(img, b1 | b2, vox)
r = cd.decompose_experimental(cand, img, vox)
check("4a equal bands: both bands in the core", min(recall(r["core"], b1), recall(r["core"], b2)) >= 0.7,
      f"recall {recall(r['core'], b1):.2f} / {recall(r['core'], b2):.2f}")
img = render([(b1, 5.0), (b2, 1.7)], shape, vox, 9005, blur_mm=0.4); cand = candidate_from(img, b1 | b2, vox)
r = cd.decompose_experimental(cand, img, vox)
rw = recall(r["core"], b2); check("4b strong+weak: strong band kept", recall(r["core"], b1) >= 0.8, f"strong {recall(r['core'], b1):.2f}")
check("4b strong+weak: candidate mask returned unchanged (weak band never lost from the record)", np.array_equal(r["candidate"], cand))
check("4b strong+weak: weak band not in core is kept as support", ((b2 & cand & ~r["core"]) <= r["support"]).all())
print(f"INFO  4b weak band core recall {rw:.2f}")
if rw < 0.7: limit("4b weak band next to a strong one is lost from the core", f"weak recall {rw:.2f} (v5.13 PH6 #1 behaviour)")
gap = cand & ~ndi.binary_dilation(b1 | b2, iterations=1)
print(f"INFO  4b gap voxels between bands in core: {(r['core'] & gap).sum()} of {gap.sum()}")

# 5 unstable cores: shallow profile (heavy blur, low contrast) vs sharp
img_s = render([(band, 3.0)], shape, vox, 9006, blur_mm=0.4); img_w = render([(band, 1.3)], shape, vox, 9006, blur_mm=2.0)
rs = cd.decompose_experimental(candidate_from(img_s, band, vox), img_s, vox)
rw_ = cd.decompose_experimental(candidate_from(img_w, band, vox, z=1.5), img_w, vox)
us, uw = rs["core_unstable_frac"], rw_["core_unstable_frac"]
check("5 unstable: fraction reported in [0, 1]", us is not None and 0 <= us <= 1 and (uw is None or 0 <= uw <= 1))
check("5 unstable: shallow profile at least as unstable as sharp", uw is None or uw >= us, f"sharp {us:.2f} shallow {uw if uw is None else round(uw, 2)}")
check("5 unstable voxels lie inside the 1-voxel zone", not (rs["unstable"] & ~ndi.binary_dilation(rs["candidate"], cd.S26)).any())
if us > 0.3: limit("5 sharp core still has many unstable voxels", f"{us:.2f}")

# 6 low contrast and PURE NOISE (no deposit): does the core gate (local max of c >= 3) reject noise?
fr = []
for sd_ in range(5):
    img = render([], shape, vox, 9200 + sd_); r = cd.decompose_experimental(band.copy(), img, vox)
    fr.append(r["core"][band].mean() if r["status"] != "unavailable" else 0)
print(f"INFO  6 pure noise: share of candidate called core {np.mean(fr):.2f} (5 seeds)")
check("6 pure noise: core share reported (measured)", all(0 <= f <= 1 for f in fr))
if np.mean(fr) > 0.05: limit("6 noise forms a core: the >= 3 gate is on the LOCAL MAXIMUM of c, which pure noise reaches",
                             f"{np.mean(fr):.2f} of a deposit-free candidate becomes core; core presence alone is not evidence")

# 7 shell too small -> unavailable, candidate returned
cand = np.ones((6, 6, 4), bool); img = np.full(cand.shape, 50.0)
r = cd.decompose_experimental(cand, img, vox)
check("7 shell too small: status unavailable", r["status"] == "unavailable" and np.array_equal(r["candidate"], cand), r.get("reason", ""))

# 8 inputs unchanged, determinism, adjacent object, anisotropic voxels
img = render([(band, 3.0)], shape, vox, 9008, blur_mm=0.4); cand = candidate_from(img, band, vox)
blob = ((X - c0[0] - 4.0) ** 2 + (Y - c0[1]) ** 2 + (Z - c0[2]) ** 2) <= 1.0
img[blob] = 100 - 6 * 5.0
i0, c0m = img.copy(), cand.copy(); a = cd.decompose_experimental(cand, img, vox); b = cd.decompose_experimental(cand, img, vox)
check("8 inputs not modified", np.array_equal(img, i0) and np.array_equal(cand, c0m))
check("8 deterministic", all(np.array_equal(a[k], b[k]) for k in ("core", "support", "adjacent", "unstable")))
check("8 separate dark blob reported as adjacent, not core", (a["adjacent"] & blob).sum() > 0 and not (a["core"] & blob).any(),
      f"adjacent {(a['adjacent'] & blob).sum()} core {(a['core'] & blob).sum()}")
va = np.array([0.5, 0.5, 2.0]); sa = (60, 60, 16); Ga = grid(sa, va); ca = np.array(sa) * va / 2
ba = (np.abs(Ga[..., 0] - ca[0]) <= 0.5) & (np.abs(Ga[..., 1] - ca[1]) <= 8) & (np.abs(Ga[..., 2] - ca[2]) <= 5)
img = render([(ba, 3.0)], sa, va, 9009, blur_mm=0.4); r = cd.decompose_experimental(candidate_from(img, ba, va), img, va)
check("8 anisotropic 0.5x0.5x2 mm: core recalls the band", recall(r["core"], ba) >= 0.7, f"recall {recall(r['core'], ba):.2f}")

# 10 masked image edge: the detector SWI is 0 outside the brain mask; zeros must not become core
img = render([(band, 3.0)], shape, vox, 9010, blur_mm=0.4); cand = candidate_from(img, band, vox)
brain = X < c0[0] + 1.5                                    # mask boundary 1 mm beyond the band
masked = img * brain
r0 = cd.decompose(cand.copy(), masked.astype(np.float64), vox)          # verbatim function, unprepared input
r = cd.decompose_experimental(cand, masked, vox, valid=brain)
z0 = int((r0["core"] & ~brain).sum()); rc0 = recall(r0["core"], band)
print(f"INFO  10 verbatim on masked input: {z0} masked voxels in core, deposit recall {rc0:.2f}")
check("10 masked edge: no masked-out voxel in the core", not (r["core"] & ~brain).any(), f"filled {r['masked_voxels_filled']}")
check("10 masked edge: deposit recall kept", recall(r["core"], band) >= 0.8, f"recall {recall(r['core'], band):.2f}")
if z0 > 0: limit("10 verbatim decompose() treats masked zeros as maximal darkness (fixed by input preparation in the wrapper)", f"{z0} voxels")

# 9 measured regime (reported, not asserted): recall and pieces vs contrast
for nm, t, ks in (("band 1 mm", band, (1, 2, 3, 5)), ("tube 0.5 mm", tube, (1, 2, 3, 5))):
    for blur in (0.4, 0.8):
        for k in ks:
            img = render([(t, k)], shape, vox, 9300 + k, blur_mm=blur); r = cd.decompose_experimental(candidate_from(img, t, vox), img, vox)
            if r["status"] == "unavailable": print(f"REGIME  {nm} k{k} blur {blur}: unavailable"); continue
            print(f"REGIME  {nm} blur {blur} mm k{k}: deposit median c {np.median(r['c'][t]):5.1f}  core recall {recall(r['core'], t):.2f}"
                  f"  pieces {ndi.label(r['core'], cd.S26)[1]}  unstable {r['core_unstable_frac'] if r['core_unstable_frac'] is None else round(r['core_unstable_frac'], 2)}")

print(f"\ncore_decompose: {len(FAILS)} FAIL, {len(LIMITS)} known limits reported (experimental, not ground truth)")
sys.exit(1 if FAILS else 0)
