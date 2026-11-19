"""check_uscore_features.py - unit tests of each of the five predictors and their reliability states, on simple analytic
geometry (flat pial surface at z = 12 mm, brain below z = 15 mm). Independent of the adversarial scenes. Seeds 6001+.
usage: python tests/check_uscore_features.py (exit 1 on FAIL)"""
import os, sys
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(H), "unified_score"))
import numpy as np
from scipy import ndimage as ndi
from uscore import features as fe

FAILS = []
def check(n, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else FAILS.append(n))

vox = np.array([0.5, 0.5, 0.5]); sh = (60, 60, 44)
G = np.stack(np.meshgrid(*[np.arange(n) * v for n, v in zip(sh, vox)], indexing="ij"), -1); X, Y, Z = G[..., 0], G[..., 1], G[..., 2]
PIAL = 12.0; psd = (Z - PIAL).astype(np.float32); brain = Z < 15.0
edge = np.zeros(sh, bool); edge[[0, -1]] = edge[:, [0, -1]] = edge[:, :, [0, -1]] = True

def scene(dep, seed, k=3.0, raw_extra=None):
    rng = np.random.default_rng(seed); d = ndi.gaussian_filter(dep * k * 12.0, 0.4 / vox)
    raw = 100 - d + rng.normal(0, 4, sh)
    if raw_extra is not None: raw = raw_extra(raw)
    return raw.astype(np.float32), (raw * brain).astype(np.float32)

plate = (np.abs(Z - (PIAL - 1.0)) <= 0.3) & (np.abs(X - 15) <= 5) & (np.abs(Y - 15) <= 4)
raw, img = scene(plate, 6001); cand = plate.copy()
F, D = fe.extract(cand, img, vox, raw=raw, ves=np.zeros(sh, bool), psd=psd, brain=brain, reg="ok", crop_edge=edge)
# x2
check("x2 reliable on a clear plate, several noise units", F["x2_core_contrast_nu"]["status"] == "reliable" and F["x2_core_contrast_nu"]["value"] > 5, F["x2_core_contrast_nu"]["value"])
F0, _ = fe.extract(cand, (100 + np.random.default_rng(6002).normal(0, 4, sh)).astype(np.float32) * brain, vox, psd=psd, brain=brain, reg="ok", crop_edge=edge)
check("x2 no deposit -> not reliable (never 'reliable low')", F0["x2_core_contrast_nu"]["status"] != "reliable", F0["x2_core_contrast_nu"]["reasons"])
Fs, _ = fe.extract(np.ones((6, 6, 4), bool), np.full((6, 6, 4), 50.0), vox)
check("x2 shell too small -> unavailable", Fs["x2_core_contrast_nu"]["status"] == "unavailable")
# x3
v3 = F["x3_pial_distance_mm"]["value"]
check("x3 = known depth (-1.0 mm) within half a voxel", abs(v3 + 1.0) <= 0.3, v3)
Fn, _ = fe.extract(cand, img, vox, psd=None, brain=brain, reg="ok", crop_edge=edge)
check("x3 / x4 unavailable without anatomy", Fn["x3_pial_distance_mm"]["status"] == "unavailable" and Fn["x4_sulcal_alignment"]["status"] == "unavailable")
Fr, _ = fe.extract(cand, img, vox, psd=psd, brain=brain, reg="unreliable", crop_edge=edge)
check("x3 unreliable under bad registration (value kept)", Fr["x3_pial_distance_mm"]["status"] == "unreliable" and Fr["x3_pial_distance_mm"]["value"] is not None)
Fm, _ = fe.extract(cand, img, vox, psd=psd, brain=brain, reg="marginal", crop_edge=edge)
check("x3 reliable / x4 unreliable at marginal registration (sulcal direction is stricter)",
      Fm["x3_pial_distance_mm"]["status"] == "reliable" and Fm["x4_sulcal_alignment"]["status"] == "unreliable")
# x4
check("x4 sheet lying in the surface ~ 1", F["x4_sulcal_alignment"]["status"] == "reliable" and F["x4_sulcal_alignment"]["value"] > 0.9,
      (F["x4_sulcal_alignment"]["value"], F["x4_sulcal_alignment"]["extra"].get("mode")))
rad = (np.hypot(X - 15, Y - 15) <= 0.6) & (Z > PIAL - 3) & (Z < PIAL + 2)
r2, i2 = scene(rad, 6003); F4, _ = fe.extract(rad, i2, vox, psd=psd, brain=brain, reg="ok", crop_edge=edge)
check("x4 tube crossing the surface ~ 0", F4["x4_sulcal_alignment"]["value"] is not None and F4["x4_sulcal_alignment"]["value"] < 0.2,
      (F4["x4_sulcal_alignment"]["value"], F4["x4_sulcal_alignment"]["status"]))
ball = ((X - 15) ** 2 + (Y - 15) ** 2 + (Z - (PIAL - 1.5)) ** 2) <= 1.5 ** 2
r3, i3 = scene(ball, 6004); F5, _ = fe.extract(ball, i3, vox, psd=psd, brain=brain, reg="ok", crop_edge=edge)
check("x4 ball: direction undefined -> unreliable", F5["x4_sulcal_alignment"]["status"] == "unreliable", F5["x4_sulcal_alignment"]["reasons"])
# x1
line = lambda y0, y1: (np.hypot(X - 15, Z - (PIAL + 0.8)) <= 0.8) & (Y >= y0) & (Y <= y1)
ves = line(0, 30); cv = line(12, 18); r4, i4 = scene(ves, 6005)
F6, _ = fe.extract(cv, i4, vox, ves=ves, psd=psd, brain=brain, reg="ok", crop_edge=edge)
e = F6["x1_vessel_continuity_mm"]
check("x1 vessel entering and exiting: traverse, ~ sum of the two reaches (12 + 12 mm, minus zone)", e["extra"]["traverse"] and 18 <= e["value"] <= 25, (e["value"], e["extra"]["reaches"]))
check("x1 censored at the crop border is a NOTE, status stays reliable", e["status"] == "reliable" and e["extra"]["censored"])
F7, _ = fe.extract(cv, i4, vox, ves=line(12, 30), psd=psd, brain=brain, reg="ok", crop_edge=edge)
check("x1 vessel on one side only: contact without traverse -> 0", F7["x1_vessel_continuity_mm"]["value"] == 0 and F7["x1_vessel_continuity_mm"]["extra"]["contact"])
F8, _ = fe.extract(cand, img, vox, ves=None, psd=psd, brain=brain, reg="ok", crop_edge=edge)
check("x1 no vessel map -> unavailable (not 0)", F8["x1_vessel_continuity_mm"]["status"] == "unavailable" and F8["x1_vessel_continuity_mm"]["value"] is None)
check("x1 no vessel near -> 0, no contact", F["x1_vessel_continuity_mm"]["value"] == 0 and not F["x1_vessel_continuity_mm"]["extra"]["contact"])
# x5
band = (np.abs(X - 15) <= 0.5) & (np.abs(Y - 15) <= 4) & (Z > PIAL - 2) & (Z < 20.5)
r5, i5 = scene(band, 6006); F9, _ = fe.extract(band & brain, i5, vox, raw=r5, psd=psd, brain=brain, reg="ok", crop_edge=edge)
v5 = F9["x5_extracranial_mm"]["value"]
check("x5 band continuing 5.5 mm beyond the brain mask: measured 5.5 .. 7.5 mm (blooming adds length)", 5.0 <= v5 <= 7.5, v5)
print(f"KNOWN-BIAS  x5 overestimates by {v5 - 5.5:+.1f} mm here (blur / noise attached to the band end; first run: +1.5 mm). Documented in FEATURE_SPEC.")
voidf = lambda r: np.where(Z >= 15.5, 2.0, r)
r6, i6 = scene(band, 6007, raw_extra=voidf); F10, _ = fe.extract(band & brain, i6, vox, raw=r6, psd=psd, brain=brain, reg="ok", crop_edge=edge)
check("x5 signal void beyond the mask is not 'continuation'", F10["x5_extracranial_mm"]["value"] <= 1.0, F10["x5_extracranial_mm"]["value"])
check("x5 without unmasked SWI -> unavailable", F8["x5_extracranial_mm"]["status"] == "unavailable")
check("x5 confined plate -> 0", F["x5_extracranial_mm"]["value"] == 0)
# x4 audit (cycle 2): line-mode x4 is surface TANGENCY, not alignment with the sulcal axis; x4b (exploratory) measures the latter
sys.path.insert(0, H); import uscore_synth as sy
lines = {"along": (np.abs(sy.X - (sy.SULC_X - sy.SULC_W / 2 - 0.4)) <= 0.3) & (np.abs(sy.Y - 18) <= 7) & (np.abs(sy.Z - (sy.PIAL_Z - 4)) <= 0.3),
         "across": (np.abs(sy.Y - 18) <= 0.3) & (np.abs(sy.X - 14) <= 5) & (np.abs(sy.Z - (sy.PIAL_Z - 0.4)) <= 0.3) & ~sy.SULC,
         "flat": (np.abs(sy.Y - 18) <= 0.3) & (np.abs(sy.X - 36) <= 4) & (np.abs(sy.Z - (sy.PIAL_Z - 0.4)) <= 0.3)}
X4 = {}
for nm, mk in lines.items():
    rw, im = sy.render([(mk, 3.0)], 7700); Fx, _ = fe.extract(mk, im, sy.VOX, raw=rw, psd=sy.PSD, brain=sy.BRAIN, reg="ok"); X4[nm] = Fx
check("x4 audit: line-mode x4 cannot tell along-sulcus from across-sulcus (both ~1: it measures surface tangency)",
      abs(X4["along"]["x4_sulcal_alignment"]["value"] - X4["across"]["x4_sulcal_alignment"]["value"]) < 0.1,
      f"{X4['along']['x4_sulcal_alignment']['value']:.2f} vs {X4['across']['x4_sulcal_alignment']['value']:.2f}")
check("x4b (exploratory): along the sulcus ~1", (X4["along"]["x4b_sulcal_axis_exploratory"]["value"] or 0) > 0.9, X4["along"]["x4b_sulcal_axis_exploratory"]["value"])
check("x4b (exploratory): across the sulcus ~0", X4["across"]["x4b_sulcal_axis_exploratory"]["value"] is not None and X4["across"]["x4b_sulcal_axis_exploratory"]["value"] < 0.2,
      X4["across"]["x4b_sulcal_axis_exploratory"]["value"])
check("x4b (exploratory): flat convexity -> unavailable (no sulcal axis), never a value", X4["flat"]["x4b_sulcal_axis_exploratory"]["status"] == "unavailable")
from uscore.common import PREDICTORS
check("x4b is NOT a model predictor", "x4b_sulcal_axis_exploratory" not in PREDICTORS)

# general
check("every feature has a status in the three states", all(F[k]["status"] in ("reliable", "unreliable", "unavailable") for k in fe.FEATURE_SPEC))
check("candidate never modified", np.array_equal(cand, plate))
check("spec documents units, inputs, reliability, missing data, failure modes for all five",
      all(set(v) >= {"unit", "range", "inputs", "reliable_if", "missing", "failure_modes"} for v in fe.FEATURE_SPEC.values()) and len(fe.FEATURE_SPEC) == 5)
print(f"\nuscore features: {len(FAILS)} FAIL")
sys.exit(1 if FAILS else 0)
