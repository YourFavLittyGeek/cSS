"""core_decompose.py - EXPERIMENTAL dark-core / blooming-support decomposition of ONE candidate (unified-score project).

Provenance (isolated import, not a branch merge):
  source file      cSS_pipeline_v4.13/scripts/css_morph3d_v2.py  (v5.13, uncommitted, branch experimental/morphology-v513)
  source sha256    128d5ae18ae17fb97508d3f251743f10e6cd94e5bba294e51383912449b6bfe7
  copied lines     62-85 (function decompose) + the constant S26 (line 18), verbatim
  function sha256  bbebcf37035ee2e6eac1fd766ea46191e2b12394e256b9ffdc9c1bc14ad4cabd   (sha256 of those 24 source lines; tests/check_core_decompose.py re-checks it)
  copied on        2026-11-19
Dependencies: numpy, scipy.ndimage only (no css_morph3d, css_morph3d_v2 or phantom code).

The output is EXPERIMENTAL measurement, NOT ground truth. Known limits (v5.13 report): about 35 % of blooming remains in the
core; about 33 % of core voxels are unstable; a thin band next to a stronger one can be lost (tram-track, PH6 #1); the noise
sigma comes from a 2-5 mm shell that on real SWI mixes tissues (untested on real data); the core may extend one voxel
outside the candidate. The original candidate mask is never modified and is returned unchanged as 'candidate'."""
import numpy as np
from scipy import ndimage as ndi

S26 = ndi.generate_binary_structure(3, 3)

STATUS = "experimental"


# ---- verbatim copy of css_morph3d_v2.decompose (do not edit; see provenance) ----
def decompose(cand, img, vox, shell=(2.0, 5.0), r_peak=2.0):
    vox = np.asarray(vox, float); cand = np.asarray(cand, bool)
    dist = ndi.distance_transform_edt(~cand, sampling=vox)
    S = (dist >= shell[0]) & (dist <= shell[1])
    if S.sum() < 20: return dict(error="background shell too small")
    s = img[S]; med = np.median(s); mad = 1.4826 * np.median(np.abs(s - med)) + 1e-6
    s2 = s[s >= med - 2 * mad]; mu = float(np.median(s2)); sd = float(1.4826 * np.median(np.abs(s2 - np.median(s2))) + 1e-6)
    c = (mu - img) / sd
    fp = np.ones([max(1, int(np.ceil(r_peak / v))) * 2 + 1 for v in vox], bool)
    gg = np.indices(fp.shape).astype(float); ctr = (np.array(fp.shape) - 1) / 2
    fp = (((gg - ctr[:, None, None, None]) * vox[:, None, None, None]) ** 2).sum(0) <= r_peak ** 2
    cpk = ndi.maximum_filter(c, footprint=fp)
    zone = ndi.binary_dilation(cand, S26)
    ok = zone & (cpk >= 3)
    core = ok & (c >= 0.5 * cpk)
    unstable = ok & (((c >= 0.4 * cpk) != (c >= 0.6 * cpk)) | (np.abs(c - 0.5 * cpk) < 1))
    lowc = zone & (cpk < 3)
    support = cand & ~core
    dark = (c >= 3) & (dist <= shell[1]) & ~cand
    dl, nd = ndi.label(dark, S26); touch = np.unique(dl[ndi.binary_dilation(cand | core, S26) & (dl > 0)])
    adjacent = (dl > 0) & ~np.isin(dl, touch)
    return dict(core=core, support=support, adjacent=adjacent, unstable=unstable, lowc=lowc, c=c, mu=mu, sd=sd,
                core_unstable_frac=float(unstable[core].mean()) if core.any() else None,
                lowc_frac=float(lowc[cand].mean()) if cand.any() else None)
# ---- end of verbatim copy ----


def decompose_experimental(cand, img, vox, shell=(2.0, 5.0), r_peak=2.0, valid=None):
    """Wrapper: works on copies (inputs never modified), keeps the original candidate mask, and labels the result.
    valid: optional bool mask of voxels that carry image signal (e.g. the brain mask). Masked-out voxels (value 0 in the
    detector's brain-masked SWI) would read as maximal darkness inside decompose(); they are filled with the median of the
    valid 2-5 mm shell BEFORE the verbatim function runs and removed from core / unstable / adjacent afterwards (input
    preparation only; the verbatim algorithm is unchanged). Default: valid = img != 0 when the image contains exact zeros.
    Returns dict with candidate (unchanged copy), core, support (= candidate minus core: the blooming / support part),
    adjacent, unstable, lowc, core_outside_candidate (voxels), masked_voxels_filled, status, and the scalars of decompose();
    or status 'unavailable' with the reason when the background shell is too small."""
    cand0 = np.array(cand, bool, copy=True); img0 = np.array(img, np.float64, copy=True)
    if valid is None: valid = img0 != 0 if (img0 == 0).any() else np.ones(img0.shape, bool)
    valid = np.asarray(valid, bool); nfill = int((~valid).sum())
    if nfill:
        dist = ndi.distance_transform_edt(~cand0, sampling=np.asarray(vox, float))
        sh = (dist >= shell[0]) & (dist <= shell[1]) & valid
        if sh.sum() < 20: return dict(status="unavailable", reason="background shell too small (valid voxels)", candidate=cand0, label=STATUS)
        img0[~valid] = np.median(img0[sh])
    out = decompose(cand0, img0, vox, shell=shell, r_peak=r_peak)
    if "error" in out:
        return dict(status="unavailable", reason=out["error"], candidate=cand0, label=STATUS)
    for k in ("core", "unstable", "adjacent", "lowc"): out[k] = out[k] & valid
    out["support"] = cand0 & ~out["core"]
    out["core_unstable_frac"] = float(out["unstable"][out["core"]].mean()) if out["core"].any() else None
    out["candidate"] = cand0
    out["core_outside_candidate"] = int((out["core"] & ~cand0).sum())
    out["masked_voxels_filled"] = nfill
    out["status"] = "ok" if out["core"].any() else "no_core"
    out["label"] = STATUS
    return out
