"""Phantom tests of the experimental structural modules (16 categories). Synthetic only: a pass shows that the code
does what its definition says on constructed shapes - NOT clinical validity.
Usage: python -m structural_detection.tests.test_structural [OUT_DIR]   (exit 1 on any failure)"""
import sys, os, json, time, subprocess, hashlib, numpy as np
from scipy import ndimage as ndi
from .. import phantoms as P, hessian_fingerprint as A, candidate_decomposition as F, surface_coordinates as B
from .. import vessel_graph as C, multiview_seeding as D, sulcus_reference as E, fusion as FU
from ..common import hessian_eigs

OUT = sys.argv[1] if len(sys.argv) > 1 else None
results = []
def check(cat, name, cond, **vals):
    results.append(dict(category=cat, test=name, passed=bool(cond), **{k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else v) for k, v in vals.items()}))
    print(("PASS " if cond else "FAIL ") + f"[{cat}] {name} " + " ".join(f"{k}={v:.3g}" if isinstance(v, (float, np.floating)) else f"{k}={v}" for k, v in vals.items()))

def fp(img, m, vox=(0.5, 0.5, 0.5), scales=A.SCALES_MM):
    mp = A.voxel_maps(img, vox, m, scales); return A.object_features(mp, np.ones(int(m.sum()), bool), vox), mp

V = (0.5, 0.5, 0.5)
# 1 plate
im, m = P.plate(); f, _ = fp(im, m)
check("01_plate", "plate reads sheet-like", f["tube_ratio_signed_med"] < 0.2 and f["hf_plate_minus_tube"] > 0.5, tube=f["tube_ratio_signed_med"], pmt=f["hf_plate_minus_tube"])
# 2 tube
im, m = P.tube(); f, _ = fp(im, m)
check("02_tube", "tube reads tube-like", f["tube_ratio_signed_med"] > 0.55 and f["hf_plate_minus_tube"] < -0.5, tube=f["tube_ratio_signed_med"], pmt=f["hf_plate_minus_tube"])
# 3 blob
im, m = P.blob(); f, _ = fp(im, m)
check("03_blob", "blob has blob voxels and highest ratio", f["hf_blob_frac"] >= 0.2 and f["tube_ratio_signed_med"] > 0.8, blob=f["hf_blob_frac"], tube=f["tube_ratio_signed_med"])
# 4 curved sheet (cSS along a curved gyrus)
im, m = P.curved_sheet(); f, _ = fp(im, m)
check("04_curved_sheet", "curved band stays sheet-like", f["tube_ratio_signed_med"] < 0.3 and f["hf_plate_minus_tube"] > 0.3, tube=f["tube_ratio_signed_med"], pmt=f["hf_plate_minus_tube"])
# 5 tram-track
im, m = P.tram_track(); f, _ = fp(im, m)
check("05_tram_track", "two parallel plates read sheet-like", f["tube_ratio_signed_med"] < 0.3, tube=f["tube_ratio_signed_med"], pmt=f["hf_plate_minus_tube"])
# 6 fragmented sheet: per-voxel shape preserved; decomposition keeps every voxel
im, m = P.fragmented_sheet(); f, mp = fp(im, m)
cls = np.full(m.shape, -1, np.int8); cls[mp["idx"]] = mp["cls"]; comp, rows = F.decompose(m, cls, V)
check("06_fragmented", "fragmented sheet still sheet-like, all voxels kept", f["tube_ratio_signed_med"] < 0.35 and ((comp > 0) == m).all(),
      tube=f["tube_ratio_signed_med"], n_comp=len(rows))
# 7 orientation invariance (oblique plate / oblique tube vs axis-aligned)
im, m = P.oblique_plate(n=(1, 2, 1.5)); f1, _ = fp(im, m); im, m = P.plate(); f0, _ = fp(im, m)
im, m = P.tube(direction=(1, 1, 1)); t1, _ = fp(im, m); im, m = P.tube(); t0, _ = fp(im, m)
check("07_orientation", "oblique plate and tube keep their class", f1["hf_plate_minus_tube"] > 0.5 and t1["hf_plate_minus_tube"] < -0.3
      and abs(t1["tube_ratio_signed_med"] - t0["tube_ratio_signed_med"]) < 0.15, plate_oblique=f1["tube_ratio_signed_med"], tube_oblique=t1["tube_ratio_signed_med"], tube_axis=t0["tube_ratio_signed_med"])
# 8 anisotropic voxels: 0.5 x 0.5 x 3 mm (factor 6)
im, m = P.plate(shape=(48, 48, 72), thick_mm=1.0, size_mm=(14, 14), normal_axis=0); ia, ma = P.resample_z(im, m, 6)
fa, _ = fp(ia, ma, (0.5, 0.5, 3.0))
im, m = P.tube(shape=(48, 48, 72), direction=(0, 1, 0), length_mm=18); ib, mb = P.resample_z(im, m, 6, thr=0.15); tb, _ = fp(ib, mb, (0.5, 0.5, 3.0))
check("08_anisotropy", "3 mm slices: plate stays below tube; unreliable scales flagged", fa["tube_ratio_signed_med"] < tb["tube_ratio_signed_med"]
      and fa["aniso_unreliable_scales"] != "none", plate=fa["tube_ratio_signed_med"], tube=tb["tube_ratio_signed_med"], flagged=fa["aniso_unreliable_scales"])
# 9 noise
im, m = P.plate(noise=0.05, seed=1); fn, _ = fp(im, m); im, m = P.tube(noise=0.05, seed=1); tn, _ = fp(im, m)
check("09_noise", "5 % noise: plate < 0.35 < tube", fn["tube_ratio_signed_med"] < 0.35 and tn["tube_ratio_signed_med"] > 0.45, plate=fn["tube_ratio_signed_med"], tube=tn["tube_ratio_signed_med"])
# 10 merged plate + tube -> decomposition
im, pl, tb_ = P.sheet_plus_tube(); m = pl | tb_; _, mp = fp(im, m)
cls = np.full(m.shape, -1, np.int8); cls[mp["idx"]] = mp["cls"]; comp, rows = F.decompose(m, cls, V); sm = F.summary(rows)
pk = [r for r in rows if r["comp_kind"] == "plate"]; plate_cov = max(((comp == r["comp_id"]) & pl).sum() / pl.sum() for r in pk) if pk else 0
check("10_splitting", "merged object -> plate + tube components, union preserved, plate covered", sm["dec_mixed_object"] and ((comp > 0) == m).all() and plate_cov > 0.7,
      n_comp=sm["dec_n_components"], plate_coverage=plate_cov)
# 10b splitting never loses voxels on random shapes
rng = np.random.default_rng(5); ok = True
for _ in range(5):
    mm = ndi.binary_dilation(rng.random((30, 30, 30)) > 0.995, iterations=2); cc = rng.integers(0, 6, mm.shape).astype(np.int8)
    cmp_, _r = F.decompose(mm, cc, V); ok &= ((cmp_ > 0) == mm).all()
check("10_splitting", "invariant on random objects (5 draws)", ok)
# 11 branching vessel -> graph
im, m = P.branching_vessel(); mp = A.voxel_maps(im, V, np.ones(im.shape, bool), (0.6, 0.8, 1.2))
cls = mp["cls"].reshape(im.shape); vm = C.vessel_map(im, cls, np.ones(im.shape, bool)); sk, deg, L = C.skeleton_graph(vm, V)
seed = np.zeros(im.shape, bool); c = np.array(im.shape) // 2; seed[c[0] - 2:c[0] + 3, c[1] - 12:c[1] - 8, c[2] - 2:c[2] + 3] = True
g = C.object_features(seed & m, sk, deg, L, V)
check("11_vessel_graph", "trunk piece connects to the Y: continuation >= 6 mm, >= 1 branch point", g["vg_connected"] and g["vg_ext_length_mm"] >= 6 and g["vg_ext_branch_points"] >= 1,
      ext_mm=g["vg_ext_length_mm"], branches=g["vg_ext_branch_points"])
# 12 isolated plate -> no connection, and that alone is NOT cSS evidence
im, m = P.plate(); mp = A.voxel_maps(im, V, np.ones(im.shape, bool), (0.6, 0.8, 1.2)); cls = mp["cls"].reshape(im.shape)
vm = C.vessel_map(im, cls, np.ones(im.shape, bool)); sk, deg, L = C.skeleton_graph(vm, V); g = C.object_features(m, sk, deg, L, V)
cat, _ = FU.categorise(dict(vg_evidence=g["vg_evidence"]))
check("12_no_connection", "isolated plate: no detectable connection; fusion with only that -> not cSS", g["vg_evidence"] == "no_detectable_connection" and cat != "css_supporting",
      ext_mm=g["vg_ext_length_mm"], fusion=cat)
# 13 multi-view: plate lying IN the axial plane (normal = z)
im, m = P.plate(shape=(48, 48, 32), normal_axis=2, size_mm=(12, 12), noise=0.02, seed=4); mask = ndi.binary_dilation(m, iterations=8)
inner = ndi.binary_erosion(m, structure=np.ones((7, 7, 1)))            # plate interior (away from its rim)
Vt, per, vv = D.votes(im, mask, V); ax_hit = per[2][inner].mean(); other = max(per[0][inner].mean(), per[1][inner].mean())
_, srows = D.seed_components(Vt, per, V, None)
check("13_multiview", "in-plane sheet found by coronal/sagittal views more than by axial", other > ax_hit + 0.3 and any(r["status"] == "new" for r in srows),
      axial_hit=ax_hit, cor_sag_hit=other, seeds=len(srows))
check("13_multiview", "view validity: 0.8x0.8x3 mm -> axial only", D.valid_views((0.8, 0.8, 3.0)) == [False, False, True], views=str(D.valid_views((0.8, 0.8, 3.0))))
# 14 sulcal reference: focal dark band vs region uniformly dark at the same depth
shape = (60, 60, 40); g3 = np.indices(shape); psd = (g3[0] - 30) * 0.5     # flat 'surface' at i = 30; < 0 tissue
base = np.full(shape, 1000.0, np.float32); lesion = (psd > -1.2) & (psd <= 0) & (np.abs(g3[1] - 30) < 8) & (np.abs(g3[2] - 20) < 8)
im1 = base.copy(); im1[lesion] = 500; im1 = im1 + np.random.default_rng(2).normal(0, 30, shape)
im2 = base.copy(); im2[(psd > -1.2) & (psd <= 0)] = 500; im2 = im2 + np.random.default_rng(2).normal(0, 30, shape)
r1 = E.object_features(im1, lesion, psd, V); r2 = E.object_features(im2, lesion, psd, V)
check("14_sulcal_reference", "focal lesion contrasts with same-depth neighbours; shared darkness does not", r1["sr_contrast_z"] < -3 and r1["sr_ref_dark_frac"] < 0.1
      and r2["sr_ref_dark_frac"] > 0.3 and r2["sr_contrast_z"] > -2, focal_z=r1["sr_contrast_z"], shared_z=r2["sr_contrast_z"], shared_frac=r2["sr_ref_dark_frac"])
# 15 surface coordinates: subpial band vs vessel out in CSF; tram-track normal coherence
nrm = B.normals(psd, V); s1 = B.object_features(lesion, psd, nrm, V)
ves = (np.abs(psd - 1.5) <= 0.5) & (np.abs(g3[2] - 20) <= 1) & (np.abs(g3[1] - 30) < 12); s2 = B.object_features(ves, psd, nrm, V)
check("15_surface_coords", "band: subpial, wide; vessel: in CSF, narrow", s1["sc_subpial_frac"] > 0.9 and s2["sc_csf_frac"] > 0.9 and s1["sc_tan_width_mm"] > 3 * s2["sc_tan_width_mm"],
      band_width=s1["sc_tan_width_mm"], vessel_width=s2["sc_tan_width_mm"], band_depth=s1["sc_depth_med"], vessel_depth=s2["sc_depth_med"])
psd_s = np.abs(g3[0] - 30) * 0.5 - 1.0                                     # a sulcus: CSF slab |i-30| < 2, two banks
tram = (psd_s > -1.2) & (psd_s <= -0.2) & (np.abs(g3[1] - 30) < 8) & (np.abs(g3[2] - 20) < 8)
s3 = B.object_features(tram, psd_s, B.normals(psd_s, V), V)
check("15_surface_coords", "two-bank object has low normal coherence", s3["sc_normal_coherence"] < 0.3 and s1["sc_normal_coherence"] > 0.9, tram_coh=s3["sc_normal_coherence"], band_coh=s1["sc_normal_coherence"])
# 15b surface-width reassessment: band height in slices (1.2 mm slices) vs a vessel
for nsl in (1, 2, 4, 8):
    vx = (0.5, 0.5, 1.2); shp = (60, 60, 30); gg = np.indices(shp); ps = (gg[0] - 30) * 0.5
    band = (ps > -1.2) & (ps <= 0) & (np.abs(gg[1] - 30) < 16) & (gg[2] >= 15) & (gg[2] < 15 + nsl)
    sb = B.object_features(band, ps, B.normals(ps, vx), vx)
    results.append(dict(category="15b_surface_width_resolution", test=f"band {nsl} slice(s) x 1.2 mm (descriptive)", passed=None, sc_width_mm=sb["sc_width_mm"], sc_tan_width_mm=sb["sc_tan_width_mm"]))
# 16 fusion categories on hand-made feature rows (definition check)
rows = {"css_supporting": dict(hf_plate_minus_tube=0.7, tube_ratio_signed_med=0.15, hf_blob_frac=0, sc_subpial_frac=0.9, sc_csf_frac=0.05, sc_depth_med=-0.8,
                               vg_evidence="no_detectable_connection", sr_contrast_z=-4, sr_ref_dark_frac=0.02, sr_ref_valid=True, dec_mixed_object=False),
        "vessel_supporting": dict(hf_plate_minus_tube=-0.6, tube_ratio_signed_med=0.7, hf_blob_frac=0, sc_subpial_frac=0.2, sc_csf_frac=0.8, sc_depth_med=1.2,
                                  vg_evidence="vascular_continuation", sr_contrast_z=-5, sr_ref_dark_frac=0.0, sr_ref_valid=True, dec_mixed_object=False),
        "mixed": dict(hf_plate_minus_tube=0.1, tube_ratio_signed_med=0.4, sc_subpial_frac=0.7, sc_csf_frac=0.2, sc_depth_med=-0.3, vg_evidence="vascular_continuation",
                      sr_contrast_z=-3, sr_ref_dark_frac=0.1, sr_ref_valid=True, dec_mixed_object=True),
        "microbleed_like": dict(hf_plate_minus_tube=-0.1, tube_ratio_signed_med=0.9, hf_blob_frac=0.5, sc_subpial_frac=0.3, sc_csf_frac=0.0, sc_depth_med=-2.5,
                                vg_evidence="no_detectable_connection", sr_contrast_z=-6, sr_ref_dark_frac=0.0, sr_ref_valid=True, dec_mixed_object=False),
        "normal_dark_cortex": dict(hf_plate_minus_tube=0.6, tube_ratio_signed_med=0.2, hf_blob_frac=0, sc_subpial_frac=0.9, sc_csf_frac=0.0, sc_depth_med=-1.0,
                                   vg_evidence="no_detectable_connection", sr_contrast_z=-0.8, sr_ref_dark_frac=0.45, sr_ref_valid=True, dec_mixed_object=False),
        "indeterminate": dict(hf_plate_minus_tube=0.0, tube_ratio_signed_med=0.45, hf_blob_frac=0, sc_subpial_frac=0.7, sc_csf_frac=0.1, sc_depth_med=-0.5,
                              vg_evidence="no_detectable_connection", sr_contrast_z=-2.5, sr_ref_dark_frac=0.1, sr_ref_valid=True, dec_mixed_object=False),
        "not_evaluable": dict(vg_evidence="no_detectable_connection")}
for want, r in rows.items():
    got, why = FU.categorise(r); check("16_fusion", f"definition row -> {want}", got == want, got=got)
# 16b production unchanged with flags off (runner writes nothing) - needs a prepared CSS_BASE with PH3
base = os.environ.get("CSS_STRUCT_TEST_BASE")
if base and os.path.exists(f"{base}/review/PH3_candidates.csv"):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CSS_") or k in ("CSS_BASE",)}; env["CSS_BASE"] = base
    before = set(os.listdir(base))
    r = subprocess.run([sys.executable, "-m", "structural_detection.run_structural", "PH3"], env=env, capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    check("16_production_unchanged", "flags off: runner computes and writes nothing", r.returncode == 0 and "nothing written" in r.stdout and set(os.listdir(base)) == before)
else:
    results.append(dict(category="16_production_unchanged", test="flags-off runner", passed=None, note="CSS_STRUCT_TEST_BASE not set: skipped here (run by run_all_checks.sh)"))
n_f = sum(r["passed"] is False for r in results); n_p = sum(r["passed"] is True for r in results)
print(f"\n{n_p} passed, {n_f} failed, {sum(r['passed'] is None for r in results)} skipped / descriptive")
if OUT:
    os.makedirs(OUT, exist_ok=True); json.dump(results, open(f"{OUT}/phantom_tests.json", "w"), indent=1, default=str)
sys.exit(1 if n_f else 0)
