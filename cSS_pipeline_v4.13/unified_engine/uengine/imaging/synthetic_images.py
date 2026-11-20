"""synthetic_images.py - SYNTHETIC SWI / FLAIR / label / pial-distance volumes and registration files for Stage 2 P1 tests.

The phantom is defined in WORLD coordinates (scanner RAS mm): a small ellipsoid "brain" with white matter, a 3 mm cortex, a CSF band,
radial sulci and a few dark tubular "veins"; FLAIR carries a scalp ring (it is not skull-stripped on the SWI grid, as with mri_vol2vol).
Because it is a function of world position, any grid (voxel size, storage order, obliquity) samples the same object. Nothing here is
derived from, or resembles, a patient. write_study() lays files out like a production $CSS_BASE and refuses any non-synthetic folder."""
import json, os
import numpy as np
import nibabel as nib
from scipy.spatial.transform import Rotation
from ..demo_base import MARKER, is_synthetic_base

SEMI_AXES_MM = np.array([30.0, 36.0, 26.0])
CORTEX_MM, CSF_MM = 3.0, 3.0
FOV_MM = np.array([76.0, 88.0, 64.0])


def _ramp(x, w=0.7):
    return np.clip(0.5 + x / w, 0.0, 1.0)


def signed_distance(p):
    """approximate signed distance (mm) to the brain ellipsoid: < 0 inside, > 0 outside"""
    r = np.sqrt(((p / SEMI_AXES_MM) ** 2).sum(-1))
    return (r - 1.0) * float(SEMI_AXES_MM.mean())


def _sulcus(p, d):
    az = np.arctan2(p[..., 1], p[..., 0])
    return (np.cos(8 * az + 0.3 * p[..., 2] / 10.0) > 0.93) & (d > -8.0) & (d < 0)


def _vein(p):
    c1 = np.sqrt((p[..., 0] - 12) ** 2 + (p[..., 2] - 8) ** 2) < 1.0                     # along y
    c2 = np.sqrt((p[..., 1] + 10) ** 2 + (p[..., 2] - 4) ** 2) < 0.9                     # along x
    return c1 | c2


def phantom(p, channel):
    """phantom intensity (or label / distance) at world points p [..., 3]"""
    p = np.asarray(p, float); d = signed_distance(p); sul = _sulcus(p, d)
    tex = 0.03 * np.sin(p[..., 0] / 7.0) * np.cos(p[..., 1] / 9.0) + 0.02 * np.sin(p[..., 2] / 5.0)
    wm = _ramp(-(d + CORTEX_MM)); inside = _ramp(-d); csf_band = _ramp(-(d - CSF_MM))
    if channel == "pial_sd": return np.where(sul, np.maximum(d, 0.5), d).astype(np.float32)
    if channel == "labels":
        hemi_r = p[..., 0] > 0
        lab = np.zeros(d.shape, np.int16)
        lab[(d < 0) & (d >= -CORTEX_MM)] = 3; lab[d < -CORTEX_MM] = 2
        lab[(lab == 3) & hemi_r] = 42; lab[(lab == 2) & hemi_r] = 41
        lab[sul | ((d >= 0) & (d < CSF_MM))] = 24
        return lab
    if channel == "swi":
        v = 0.45 + 0.10 * wm + tex
        v = np.where(sul, 0.8, v); v = v * inside + 0.8 * (1 - inside)
        v = np.where(_vein(p) & (d < CSF_MM), 0.1, v)
        return (v * csf_band).astype(np.float32)
    if channel == "flair":
        v = 0.70 - 0.20 * wm + tex
        v = np.where(sul, 0.1, v); v = v * inside + 0.1 * (1 - inside)
        scalp = (d > 6.0) & (d < 10.0)
        v = v * csf_band + 0.6 * scalp
        return v.astype(np.float32)
    raise ValueError(channel)


def grid_affine(vox=(0.8, 0.8, 1.2), fov_mm=FOV_MM, rot_deg=(0.0, 0.0, 0.0)):
    """RAS-stored grid centred on the phantom; rot_deg = extrinsic x, y, z rotation (oblique acquisition)"""
    vox = np.asarray(vox, float); shape = tuple(int(np.ceil(f / v)) for f, v in zip(fov_mm, vox))
    R = Rotation.from_euler("xyz", rot_deg, degrees=True).as_matrix()
    A = np.eye(4); A[:3, :3] = R @ np.diag(vox)
    A[:3, 3] = -A[:3, :3] @ ((np.array(shape) - 1) / 2.0)
    return A, shape


def sample(channel, A, shape, noise=0.0, seed=0, shift_mm=(0.0, 0.0, 0.0)):
    """the phantom sampled on a grid; shift_mm moves the CONTENT by +shift (a misregistered channel)"""
    ijk = np.indices(shape).reshape(3, -1).T.astype(float)
    W = (A[:3, :3] @ ijk.T).T + A[:3, 3] - np.asarray(shift_mm, float)
    v = phantom(W, channel).reshape(shape)
    if noise and channel in ("swi", "flair"):
        v = v + np.random.default_rng(seed).normal(0, noise, shape).astype(np.float32) * (v > 0)
    return v


def nifti(data, A, qcode=1, scode=1):
    img = nib.Nifti1Image(np.asarray(data), A)
    img.set_qform(A, code=qcode); img.set_sform(A, code=scode)
    return img


def reorient(img, axcodes):
    """the same image stored in another array order (exact permutation / flip; values unchanged)"""
    o = nib.orientations; qc, sc = int(img.header["qform_code"]), int(img.header["sform_code"])
    out = img.as_reoriented(o.ornt_transform(o.axcodes2ornt(nib.aff2axcodes(img.affine)), o.axcodes2ornt(tuple(axcodes))))
    # nibabel's as_reoriented rewrites a 0 sform code to 2 ('aligned'): keep the source's codes so a header without valid codes
    # stays without them (the geometry gate always reads the file's own header)
    out.set_qform(out.affine, code=qc); out.set_sform(out.affine, code=sc)
    return out


def _volinfo(tag, A, shape, fn):
    vs = np.linalg.norm(A[:3, :3], axis=0); D = A[:3, :3] / vs; c = A[:3, :3] @ (np.array(shape) / 2.0) + A[:3, 3]
    return (f"{tag}\nvalid = 1  # volume info valid\nfilename = {fn}\nvolume = {shape[0]} {shape[1]} {shape[2]}\n"
            f"voxelsize = {vs[0]:.15e} {vs[1]:.15e} {vs[2]:.15e}\n"
            + "".join(f"{k}   = {D[0, i]:.15e} {D[1, i]:.15e} {D[2, i]:.15e}\n" for i, k in enumerate(("xras", "yras", "zras")))
            + f"cras   = {c[0]:.15e} {c[1]:.15e} {c[2]:.15e}\n")


def write_lta(path, M_ras, src=None, dst=None, lta_type=1):
    """an LTA in FreeSurfer's text format. type 1 = RAS->RAS; type 0 = VOX->VOX (needs src / dst = (affine, shape, filename))"""
    if lta_type == 0:
        V = np.linalg.inv(dst[0]) @ M_ras @ src[0]
        body = "type      = 0 # LINEAR_VOX_TO_VOX\n"; mat = V
    else:
        body = "type      = 1 # LINEAR_RAS_TO_RAS\n"; mat = M_ras
    txt = ("# transform file (SYNTHETIC, uengine.imaging)\n" + body + "nxforms   = 1\nmean      = 0.0 0.0 0.0\nsigma     = 1.0\n1 4 4\n"
           + "\n".join(" ".join(f"{x:.15e}" for x in row) for row in mat) + "\n")
    if src is not None: txt += _volinfo("src volume info", *src)
    if dst is not None: txt += _volinfo("dst volume info", *dst)
    with open(path, "w") as f: f.write(txt + "subject synthetic\nfscale 0.100000\n")


def rigid(rot_deg=(0.0, 0.0, 0.0), trans_mm=(0.0, 0.0, 0.0)):
    M = np.eye(4); M[:3, :3] = Rotation.from_euler("xyz", rot_deg, degrees=True).as_matrix(); M[:3, 3] = trans_mm
    return M


def guard_base(base):
    """create / reuse a SYNTHETIC base only: refuse a folder that already holds non-synthetic project content"""
    if not is_synthetic_base(base):
        for d in ("data", "raw", "work", "review", "subjects", "labels"):
            p = os.path.join(base, d)
            if os.path.isdir(p) and os.listdir(p):
                raise PermissionError(f"{base} has a non-synthetic {d}/ folder - refusing to write synthetic images into it")
    os.makedirs(os.path.join(base, "unified_engine"), exist_ok=True)
    with open(os.path.join(base, MARKER), "w") as f:
        f.write("SYNTHETIC demonstration base written by uengine - no patient data\n")


def _unit(x): return np.asarray(x, float) / np.linalg.norm(x)


# synthetic candidate objects (world-defined): (list, id, kind, direction from the centre, in-plane tangent of the strip)
OBJECTS = [("candidates", 1, "css_band", (0.55, 0.25, 0.80), (0.0, 1.0, 0.0)),
           ("candidates", 2, "css_band", (-0.60, -0.20, 0.77), (0.3, 1.0, 0.0)),
           ("candidates", 3, "surface_vein", (0.20, -0.65, 0.73), (1.0, 0.0, 0.0)),
           ("candidates", 4, "surface_vein", (-0.25, 0.70, 0.67), (1.0, 0.2, 0.0)),
           ("candidates", 5, "transcortical_vein", (0.70, -0.40, 0.59), None),
           ("excluded", 1, "surface_vein", (-0.70, 0.45, 0.55), (0.0, 0.0, 1.0)),
           ("excluded", 2, "tiny", (0.05, 0.05, 1.0), None)]


def object_mask(p, kind, direction, tangent):
    """world predicate of one synthetic object (cSS band: subpial sheet strip; surface vein: tube just outside the pial surface;
    transcortical vein: radial tube crossing the cortex; tiny: a 1-2 voxel speck)"""
    p = np.asarray(p, float); d = signed_distance(p); q = p / np.linalg.norm(p, axis=-1, keepdims=True)
    k = _unit(direction)
    if kind == "tiny": return np.zeros(d.shape, bool)                       # placed voxel-wise in write_study (2 voxels)
    if kind == "transcortical_vein":
        along = (p @ k); perp = np.linalg.norm(p - along[..., None] * k, axis=-1)
        return (perp < 0.8) & (d > -6.0) & (d < 0.8) & (along > 0)
    t = _unit(np.asarray(tangent, float) - (np.asarray(tangent, float) @ k) * k); w = np.cross(k, t)
    in_strip_long = (q @ k) > np.cos(np.radians(16))
    if kind == "css_band": return in_strip_long & (np.abs(q @ w) < 0.12) & (d > -1.3) & (d < 0.0)    # sheet, ~7 mm wide
    if kind == "surface_vein": return in_strip_long & (np.abs(q @ w) < 0.022) & (d > 0.4) & (d < 1.5)
    raise ValueError(kind)


def write_study(base, sid, vox=(0.8, 0.8, 1.2), axcodes="RAS", rot_deg=(0, 0, 0), noise=0.01, seed=0, flair_shift_mm=(0, 0, 0),
                channels=("swi", "phase", "flair", "labels", "pial_sd"), t1_route=True, lta_type=0, reg_cost=0.45, acquisition=None,
                objects=True):
    """one synthetic study laid out like $CSS_BASE; returns the file paths. Channels off the list are simply absent.
    objects=True also writes review/ID_candidates|excluded.{nii.gz,csv} (detector-like tables: id + fingerprint only) and the truth
    separately to unified_engine/image_truth/ID.csv (never read by the patch extractor)."""
    if not str(sid).startswith("SYN"): raise ValueError("synthetic study codes start with SYN")
    guard_base(base)
    for d in ("data", "work", f"raw/{sid}/SWI", "review"): os.makedirs(os.path.join(base, d), exist_ok=True)
    A, shape = grid_affine(vox, rot_deg=rot_deg)
    paths = {}

    def save(ch, data, rel, dtype=None):
        img = reorient(nifti(data if dtype is None else data.astype(dtype), A), axcodes)
        p = os.path.join(base, rel); nib.save(img, p); paths[ch] = p; return img
    swi = sample("swi", A, shape, noise, seed)
    masks = {}
    if objects:
        ijk = np.indices(shape).reshape(3, -1).T.astype(float); W = (A[:3, :3] @ ijk.T).T + A[:3, 3]
        for lst, oid, kind, k, t in OBJECTS:
            m = object_mask(W, kind, k, t).reshape(shape)
            if kind == "tiny":                                                   # exactly 2 voxels: the extractor's < 3 voxel path
                c = _unit(k) / np.sqrt(((_unit(k) / SEMI_AXES_MM) ** 2).sum()) * 0.98
                v0 = np.round(np.linalg.solve(A[:3, :3], c - A[:3, 3])).astype(int)
                m = np.zeros(shape, bool); m[tuple(v0)] = True; m[tuple(v0 + [1, 0, 0])] = True
            masks[(lst, oid, kind)] = m
            swi = np.where(m, swi * 0.25, swi)                                 # dark on SWI (haemosiderin / deoxygenated blood)
    swi_img = save("swi", swi, f"data/{sid}_swi.nii")
    if objects: _write_objects(base, sid, masks, A, save, vox)
    if "phase" in channels: save("phase", sample("swi", A, shape, noise, seed + 1) - 0.5, f"data/{sid}_phase.nii.gz")
    if "flair" in channels: save("flair", sample("flair", A, shape, noise, seed + 2, shift_mm=flair_shift_mm), f"work/{sid}_flair_swispace.nii.gz")
    if "labels" in channels:
        save("labels", sample("labels", A, shape), f"work/{sid}_seg_swispace.nii.gz", np.int16)
        if t1_route: save("t1seg", sample("labels", A, shape), f"work/{sid}_t1seg_swispace.nii.gz", np.int16)
    if "pial_sd" in channels: save("pial_sd", sample("pial_sd", A, shape), f"work/{sid}_pial_sd.nii.gz")
    swi_geo = (swi_img.affine, swi_img.shape, f"data/{sid}_swi.nii")
    if t1_route:
        t1A, t1shape = grid_affine((1.0, 1.0, 1.0))
        write_lta(os.path.join(base, f"work/{sid}_swi2t1.lta"), rigid((1.0, -0.5, 0.8), (1.5, -2.0, 0.7)),
                  src=swi_geo, dst=(t1A, t1shape, f"subjects/{sid}/mri/orig.mgz"), lta_type=lta_type)
        with open(os.path.join(base, f"work/{sid}_reg.json"), "w") as f: json.dump(dict(method="bbregister", cost=reg_cost), f)
        paths["swi2t1"] = os.path.join(base, f"work/{sid}_swi2t1.lta")
    if "flair" in channels:
        fA, fshape = grid_affine((0.9, 0.9, 3.0))
        write_lta(os.path.join(base, f"work/{sid}_flair2swi.lta"), rigid((0.5, 0.0, -0.7), (-1.0, 0.5, 2.0)),
                  src=(fA, fshape, f"raw/{sid}/FLAIR/flair.nii.gz"), dst=swi_geo, lta_type=lta_type)
        paths["flair2swi"] = os.path.join(base, f"work/{sid}_flair2swi.lta")
    acq = acquisition if acquisition is not None else dict(Manufacturer="SYNTHETIC", MagneticFieldStrength=3, EchoTime=0.02,
                                                         RepetitionTime=0.028, ImageType=["ORIGINAL", "PRIMARY", "M", "SWI"],
                                                         SliceThickness=float(vox[2]), MRAcquisitionType="3D")
    with open(os.path.join(base, f"raw/{sid}/SWI/{sid}_swi.json"), "w") as f: json.dump(acq, f)
    return paths


def _write_objects(base, sid, masks, A, save, vox):
    """label maps + detector-like tables (id, fingerprint vox_i/j/k + volume_mm3, rule_version) in the STORED array order"""
    import csv
    shape = next(iter(masks.values())).shape; truth = []
    for lst, idc in (("candidates", "cand_id"), ("excluded", "excl_id")):
        lab = np.zeros(shape, np.int16)
        for (l_, oid, _), m in masks.items():
            if l_ == lst: lab[m & (lab == 0)] = oid
        img = save(f"{lst}_mask", lab, f"review/{sid}_{lst}.nii.gz", np.int16)
        L = np.asarray(img.dataobj); rows = []
        for (l_, oid, kind), _ in masks.items():
            if l_ != lst: continue
            ijk = np.argwhere(L == oid)
            if not len(ijk): continue
            near = ijk[np.argmin(np.linalg.norm(ijk - ijk.mean(0), axis=1))]
            rows.append({idc: oid, "vox_i": int(near[0]), "vox_j": int(near[1]), "vox_k": int(near[2]),
                         "volume_mm3": round(float(len(ijk) * np.prod(vox)), 3), "rule_version": "SYNTHETIC-P2"})
            if lst == "excluded": rows[-1]["reason"] = "synthetic"
            truth.append(dict(study=sid, list=lst, id=oid, kind=kind, n_vox=len(ijk)))
        cols = [idc] + (["reason"] if lst == "excluded" else []) + ["vox_i", "vox_j", "vox_k", "volume_mm3", "rule_version"]
        with open(os.path.join(base, f"review/{sid}_{lst}.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
    os.makedirs(os.path.join(base, "unified_engine", "image_truth"), exist_ok=True)
    with open(os.path.join(base, "unified_engine", "image_truth", f"{sid}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["study", "list", "id", "kind", "n_vox"]); w.writeheader(); w.writerows(truth)


def make_older(path, than, seconds=60):
    """set a file's modification time before another file's (a stale channel or registration)"""
    t = os.path.getmtime(than) - seconds; os.utime(path, (t, t))
