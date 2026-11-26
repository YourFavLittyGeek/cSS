"""second_look.py - LUMOS second look (2026-11-25, user decision): LUMOS looks at the dark spots on the cortical surface that ALBUS did not
show and SUGGESTS possible missed cSS to the reviewer. Built now, INACTIVE until LUMOS has learned from enough expert-marked missed cSS
and recognises them in patients it was not trained on (activation gate below). Accepted suggestions become missed-cSS marks (context
'lumos_suggestion'); rejected suggestions are kept as 'not cSS' image examples, so LUMOS makes fewer false suggestions after each training.

Honesty:
- a suggestion is NOT a finding and never enters a call, a score or ALBUS's candidate list;
- an accepted suggestion was AI-prompted, so it is not blind primary ground truth (the eligibility policy of call_ledger decides);
- suggestions are refused during a blind initial read (they are AI content).

find_spots(base, sid)        dark connected spots in the cortical band (|pial distance| <= BAND_MM), away from every shown / excluded
                             detector object, ranked by darkness x size -> [(key, mask, info)]
scan(base, sid, image_model) -> dict(suggestions, n_spots, ...) with the LUMOS probability of each spot (the same patch extractor)
status(model, settings)      the activation gate"""
import os
import numpy as np
import nibabel as nib
from scipy import ndimage as ndi

MIN_MARKS = 50                 # expert-marked missed cSS LUMOS has learned from
MIN_PATIENTS = 10              # ... in at least this many patients
MIN_RECALL = 0.70              # share of held-out patients' marks LUMOS recognises (P >= 0.5)
BAND_MM = 2.0                  # cortical band around the pial boundary
AWAY_VOX = 2                   # spots touching a detector object (+- this many voxels) are not suggested (that object has its own call)
MIN_VOX, MAX_VOX = 3, 3000
MAX_SPOTS = 200                # spots LUMOS looks at per study (darkest x largest first)
MAX_SUGGESTIONS = 10           # suggestions shown per study
THRESHOLD = 0.5                # LUMOS probability needed for a suggestion
VERSION = "second-look/1.0"


def status(model, settings=None):
    """-> dict(active, switched_on, ready, reasons, n_marks, n_patients, recall, gate) - active only when switched on AND ready"""
    S = settings or {}
    fam = ((model or {}).get("intelligence") or {}).get("families") or {}
    mk = (fam.get("image") or {}).get("missed_marks") or {}
    data = (model or {}).get("data") or {}; lm = data.get("lumos_missed_marks") or {}
    n = int(lm.get("used") or 0); pats = int(lm.get("patients") or 0); hc = mk.get("heldout_check") or {}; rec = hc.get("recall")
    reasons = []
    if not model: reasons.append("no trained PERCIVAL model yet")
    if model and not ((model.get("components") or {}).get("image")): reasons.append("LUMOS has no trained image model")
    if n < MIN_MARKS: reasons.append(f"LUMOS learned from {n} expert-marked missed cSS ({MIN_MARKS} needed)")
    if pats < MIN_PATIENTS: reasons.append(f"marks from {pats} patients ({MIN_PATIENTS} needed)")
    if rec is None: reasons.append("LUMOS has not checked the marks of held-out patients yet")
    elif rec < MIN_RECALL: reasons.append(f"LUMOS recognises {round(100 * rec)} % of the held-out patients' marks ({round(100 * MIN_RECALL)} % needed)")
    ready = not reasons; on = bool(S.get("lumos_second_look", True))
    return dict(active=ready and on, ready=ready, switched_on=on, reasons=reasons, n_marks=n, n_patients=pats, recall=rec,
                heldout=hc, model=(model or {}).get("version"), version=VERSION,
                gate=dict(min_marks=MIN_MARKS, min_patients=MIN_PATIENTS, min_recall=MIN_RECALL, threshold=THRESHOLD, max_suggestions=MAX_SUGGESTIONS))


def find_spots(base, sid, max_spots=MAX_SPOTS):
    swi = nib.load(os.path.join(base, "data", f"{sid}_swi.nii")); A = np.asarray(swi.dataobj, np.float32)
    psd_p = os.path.join(base, "work", f"{sid}_pial_sd.nii.gz")
    if not os.path.exists(psd_p): raise ValueError("no pial distance map (work/ID_pial_sd.nii.gz): re-run the detector")
    psd = np.asarray(nib.load(psd_p).dataobj, np.float32); brain = ndi.binary_fill_holes(A > 0)
    band = brain & (np.abs(psd) <= BAND_MM)
    if not band.any(): return []
    ref = A[band]; med = float(np.median(ref)); mad = 1.4826 * float(np.median(np.abs(ref - med))) or 1.0
    Z = (A - med) / mad
    dp = os.path.join(base, "work", f"{sid}_dark.nii.gz")
    dark = (np.asarray(nib.load(dp).dataobj) > 0) if os.path.exists(dp) else (Z < -3.0)
    taken = np.zeros(A.shape, bool)
    for lst in ("candidates", "excluded"):
        mp = os.path.join(base, "review", f"{sid}_{lst}.nii.gz")
        if os.path.exists(mp): taken |= np.asarray(nib.load(mp).dataobj) > 0
    if taken.any(): taken = ndi.binary_dilation(taken, iterations=AWAY_VOX)
    D = dark & band & ~taken
    lab, n = ndi.label(D, structure=np.ones((3, 3, 3), bool))
    if not n: return []
    idx = np.arange(1, n + 1); size = ndi.sum(D, lab, idx); mz = ndi.mean(Z, lab, idx)
    keep = [(int(i), float(sz), float(z)) for i, sz, z in zip(idx, size, mz) if MIN_VOX <= sz <= MAX_VOX]
    keep.sort(key=lambda t: t[2] * np.log1p(t[1]))                                  # darkest x largest first
    out = []
    objs = ndi.find_objects(lab)
    for i, sz, z in keep[:max_spots]:
        m = lab == i; c = np.argwhere(m).mean(0)
        out.append((f"spot_{len(out) + 1}", m, dict(vox=[int(round(v)) for v in c], n_vox=int(sz), mean_z=round(z, 2),
                                                    bbox=[[int(s.start), int(s.stop) - 1] for s in objs[i - 1]])))
    return out


def scan(base, sid, image_model, threshold=THRESHOLD, max_suggestions=MAX_SUGGESTIONS, max_spots=MAX_SPOTS):
    """LUMOS scores every spot; the best ones above the threshold are the suggestions. -> dict(suggestions=[...], maps={key: (3,U,V)}, ...)"""
    from ..imaging import patches as PT
    from .cnn import patch_maps
    spots = find_spots(base, sid, max_spots)
    if not spots: return dict(suggestions=[], maps={}, n_spots=0, version=VERSION)
    E = PT.extract_objects(base, sid, {k: m for k, m, _ in spots})
    if E["blocked"]: return dict(suggestions=[], maps={}, n_spots=len(spots), blocked=E["blocked"], version=VERSION)
    keys, M = [], []
    for k, _, _ in spots:
        if k in E["patches"]:
            mp = patch_maps(E["patches"][k])
            if mp is not None: keys.append(k); M.append(mp)
    if not keys: return dict(suggestions=[], maps={}, n_spots=len(spots), version=VERSION)
    p = 1.0 / (1.0 + np.exp(-image_model.logit_tta(np.stack(M))[0]))
    info = {k: i for k, _, i in spots}; swi = nib.load(os.path.join(base, "data", f"{sid}_swi.nii"))
    can = nib.as_closest_canonical(swi); n2c = np.linalg.inv(can.affine) @ swi.affine
    order = [j for j in np.argsort(-p) if p[j] >= threshold][:max_suggestions]
    sug = []
    for j in order:
        k = keys[j]; v = np.array(info[k]["vox"], float); c = (n2c[:3, :3] @ v + n2c[:3, 3]); w = swi.affine[:3, :3] @ v + swi.affine[:3, 3]
        sug.append(dict(key=k, p=round(float(p[j]), 3), vox=info[k]["vox"], can=[int(round(x)) for x in c], mm=[round(float(x), 1) for x in w],
                        n_vox=info[k]["n_vox"], mean_z=info[k]["mean_z"]))
    return dict(suggestions=sug, maps={keys[j]: M[j] for j in order}, n_spots=len(spots), n_scored=len(keys), threshold=threshold, version=VERSION)
