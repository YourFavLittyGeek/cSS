"""uscore_synth.py - synthetic scenes for the unified-score tests (MECHANICS ONLY; never model development or validation).
A local volume with brain tissue under a flat convexity and one sulcus (CSF slot running along y), CSF, skull (signal void),
scalp and air on the unmasked image. Deposits are dark structures blurred (blooming) with noise. Seeds 7001+."""
import numpy as np
from scipy import ndimage as ndi

VOX = np.array([0.6, 0.6, 0.6]); SHAPE = (70, 60, 66)
MU, SD = 100.0, 4.0
SULC_X, SULC_W, SULC_DEPTH = 21.0, 2.0, 10.0
PIAL_Z, BRAIN_Z, SKULL_Z, SCALP_Z = 22.0, 27.0, 31.0, 36.0     # brain mask = labels + 5 mm (as production v5.2.5)


def grid():
    return np.stack(np.meshgrid(*[np.arange(n) * v for n, v in zip(SHAPE, VOX)], indexing="ij"), -1)


G = grid(); X, Y, Z = G[..., 0], G[..., 1], G[..., 2]
SULC = (np.abs(X - SULC_X) <= SULC_W / 2) & (Z > PIAL_Z - SULC_DEPTH)
TISSUE = (Z < PIAL_Z) & ~SULC


def signed_distance(t):
    return ndi.distance_transform_edt(~t, sampling=VOX) - ndi.distance_transform_edt(t, sampling=VOX)


PSD = signed_distance(TISSUE).astype(np.float32)
BRAIN = Z < BRAIN_Z
SKULL = (Z >= BRAIN_Z) & (Z < SKULL_Z); SCALP = (Z >= SKULL_Z) & (Z < SCALP_Z); AIR = Z >= SCALP_Z


def base_raw():
    r = np.full(SHAPE, MU); r[~TISSUE & BRAIN] = 110.0; r[SKULL] = 8.0; r[SCALP] = MU; r[AIR] = 2.0
    return r


def render(deposits, seed, blur_mm=0.5, soft=None):
    """deposits: list of (mask, contrast in SD units x3). Returns raw (unmasked), img (masked)."""
    rng = np.random.default_rng(seed); dep = np.zeros(SHAPE)
    for m, k in deposits: dep = np.maximum(dep, m * k * SD * 3.0)
    dep = ndi.gaussian_filter(dep, blur_mm / VOX)
    b0 = base_raw()
    if soft is not None: b0[soft] = MU                      # soft-tissue window through the skull
    raw = b0 - dep + rng.normal(0, SD, SHAPE)
    sk = SKULL & ~soft if soft is not None else SKULL
    raw[sk] = 8.0 + rng.normal(0, 1.0, sk.sum()); raw[AIR] = np.abs(rng.normal(2.0, 1.0, AIR.sum()))
    return raw.astype(np.float32), (raw * BRAIN).astype(np.float32)


def candidate(img, truth, z=2.0, near_mm=3.0, ref_mu=MU):
    near = ndi.distance_transform_edt(~truth, sampling=VOX) <= near_mm
    dark = ((ref_mu - img) / SD >= z) & near & BRAIN
    lab, _ = ndi.label(dark, ndi.generate_binary_structure(3, 3)); keep = np.unique(lab[truth & (lab > 0)])
    return np.isin(lab, keep[keep > 0])


def tube(axis_pts, r):
    """union of balls along a polyline (list of (x,y,z) mm), radius r mm."""
    m = np.zeros(SHAPE, bool)
    for a, b in zip(axis_pts[:-1], axis_pts[1:]):
        a, b = np.array(a, float), np.array(b, float); d = b - a; L = np.linalg.norm(d)
        t = np.clip(((G - a) @ d) / (L * L), 0, 1); P = a + t[..., None] * d
        m |= np.linalg.norm(G - P, axis=-1) <= r
    return m


def scenes():
    """name -> dict(truth (cSS deposit or None), deposits, vessel map, is_css, expect, notes)"""
    S = {}
    bank = (np.abs(X - (SULC_X - SULC_W / 2 - 0.4)) <= 0.4) & (np.abs(Y - 18) <= 6) & (Z > PIAL_Z - 8) & (Z < PIAL_Z - 0.5)
    S["css_sulcal_bank"] = dict(truth=bank, deposits=[(bank, 3.0)], ves=np.zeros(SHAPE, bool), is_css=True)
    conv = (np.abs(Z - (PIAL_Z - 0.6)) <= 0.4) & (np.abs(X - 10) <= 5) & (np.abs(Y - 18) <= 4)
    S["css_convexity"] = dict(truth=conv, deposits=[(conv, 3.0)], ves=np.zeros(SHAPE, bool), is_css=True)
    vein = tube([(8, 0, PIAL_Z + 1.2), (8, 35.4, PIAL_Z + 1.2)], 1.5)
    S["surface_vein"] = dict(truth=vein, deposits=[(vein, 3.0)], ves=vein.copy(), is_css=False, alternative="surface_vein", window_y=(12, 24))
    sv = tube([(SULC_X, 0, PIAL_Z - 4), (SULC_X, 35.4, PIAL_Z - 4)], 0.9)
    S["vein_parallel_to_sulcus"] = dict(truth=sv, deposits=[(sv, 3.0)], ves=sv.copy(), is_css=False, window_y=(12, 24))
    xv = tube([(4, 18, PIAL_Z + 1.2), (16, 18, PIAL_Z + 1.2)], 1.0) | tube([(10, 0, PIAL_Z + 1.2), (10, 35.4, PIAL_Z + 1.2)], 1.0)
    S["vein_overlapping_css"] = dict(truth=conv, deposits=[(conv, 3.0), (xv, 3.0)], ves=xv.copy(), is_css=True)
    rr = np.hypot(X - 10, Y - 18); ang = np.arctan2(Y - 18, X - 10)
    arc = (np.abs(rr - 6) <= 0.35) & (ang > -0.5) & (ang < 2.6) & (np.abs(Z - (PIAL_Z - 1.5)) <= 1.2)
    S["thin_curved_css"] = dict(truth=arc, deposits=[(arc, 3.0)], ves=np.zeros(SHAPE, bool), is_css=True)
    frag = conv & ~(np.abs(X - 8) <= 0.7) & ~(np.abs(X - 12) <= 0.7)
    S["fragmented_css"] = dict(truth=frag, deposits=[(frag, 3.0)], ves=np.zeros(SHAPE, bool), is_css=True)
    b2 = (np.abs(X - (SULC_X + SULC_W / 2 + 0.4)) <= 0.4) & (np.abs(Y - 18) <= 6) & (Z > PIAL_Z - 8) & (Z < PIAL_Z - 0.5)
    S["adjacent_css_bands"] = dict(truth=bank | b2, deposits=[(bank, 3.0), (b2, 3.0)], ves=np.zeros(SHAPE, bool), is_css=True)
    mv = tube([(10, 14, PIAL_Z + 1.2), (10, 35.4, PIAL_Z + 1.2)], 1.2)
    S["mixed_vein_and_sheet"] = dict(truth=conv, deposits=[(conv, 3.0), (mv, 3.0)], ves=mv.copy(), is_css=True)
    ext = (np.abs(X - 30) <= 0.6) & (np.abs(Y - 18) <= 5) & (Z > PIAL_Z - 4) & (Z < SCALP_Z - 1)
    S["extracranial_artifact"] = dict(truth=ext, deposits=[(ext, 3.0)], ves=np.zeros(SHAPE, bool), is_css=False, alternative="extracranial_continuation",
                                      soft=SKULL & (np.abs(X - 30) <= 4) & (np.abs(Y - 18) <= 8))   # thin squama / soft-tissue window
    sk = (np.abs(Z - (BRAIN_Z - 0.6)) <= 0.5) & (np.abs(X - 34) <= 5) & (np.abs(Y - 18) <= 5)   # inner-skull band, ~4.4 mm off the pial surface
    S["skull_interface_artifact"] = dict(truth=sk, deposits=[(sk, 3.0)], ves=np.zeros(SHAPE, bool), is_css=False, alternative="skull_interface")
    # high-risk genuine cSS (added after the detector revisions, to test them on scenes they were NOT developed on)
    sub = (np.abs(Z - (PIAL_Z + 1.3)) <= 0.4) & (np.abs(X - 34) <= 5) & (np.abs(Y - 18) <= 5)
    S["css_subarachnoid_near_skull"] = dict(truth=sub, deposits=[(sub, 3.0)], ves=np.zeros(SHAPE, bool), is_css=True)
    top = (np.abs(Z - (PIAL_Z - 0.4)) <= 0.4) & (np.abs(X - 34) <= 5) & (np.abs(Y - 18) <= 5)
    thick = (np.abs(Z - (PIAL_Z + 2.4)) <= 0.4) & (np.abs(X - 34) <= 5) & (np.abs(Y - 18) <= 5)
    S["css_in_thick_csf_2.4mm"] = dict(truth=thick, deposits=[(thick, 3.0)], ves=np.zeros(SHAPE, bool), is_css=True)
    S["css_directly_under_skull"] = dict(truth=top, deposits=[(top, 3.0)], ves=np.zeros(SHAPE, bool), is_css=True)
    sv2 = tube([(SULC_X, 0, PIAL_Z - 5), (SULC_X, 35.4, PIAL_Z - 5)], 0.9)
    S["css_touching_sulcal_vein"] = dict(truth=bank, deposits=[(bank, 3.0), (sv2, 3.0)], ves=sv2.copy(), is_css=True)
    S["missing_vessel_map"] = dict(truth=conv, deposits=[(conv, 3.0)], ves=None, is_css=True)
    S["misregistration"] = dict(truth=bank, deposits=[(bank, 3.0)], ves=np.zeros(SHAPE, bool), is_css=True, shift_psd_mm=4.0)
    return S


def build(name, sc, seed):
    raw, img = render(sc["deposits"], seed, soft=sc.get("soft"))
    truth = sc["truth"]
    if sc.get("window_y"): truth = truth & (Y >= sc["window_y"][0]) & (Y <= sc["window_y"][1])   # detector-bounded candidate
    cand = candidate(img, truth)
    if sc.get("window_y"): cand &= (Y >= sc["window_y"][0] - 1) & (Y <= sc["window_y"][1] + 1)
    psd = PSD.copy(); reg = "ok"
    if sc.get("shift_psd_mm"):
        psd = ndi.shift(PSD, [0, 0, sc["shift_psd_mm"] / VOX[2]], order=1, mode="nearest"); reg = "unreliable"
    return dict(cand=cand, img=img, raw=raw, ves=sc["ves"], psd=psd, brain=BRAIN.copy(), reg=reg)
