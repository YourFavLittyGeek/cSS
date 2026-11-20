"""patches.py - candidate patches, schema css-patch/2.0 (Stage 2 P2; DATA_SCHEMA.md section 4, IMAGE_PIPELINE_DESIGN.md sections 3-4).

extract_study(base, sid, write=False) -> dict(manifest rows, patches)
  1. P1 index (index.index_study): refuses non-synthetic data; only channels with status ok / low_confidence are used; the study must
     pass the geometry gate and pial_sd must be usable (it defines the surface frame)
  2. SURFACE PATCH = css-patch/1.0, produced by scripts/surface_aligned_patch.extract_patch EXECUTED UNCHANGED (pinned sha256): same
     arrays, same keys (image_<ch>, valid_<ch>, valid, world_grid_mm, centre, u / v / n); missing channels get an all-False valid_<ch>
  3. NATIVE 2.5D STACK (new in 2.0): the object's own axial slices (centre +-2) at their acquired positions, in-plane resampled to
     0.5 mm over 32 x 32 mm; NO through-plane interpolation (the slice index is exact). Axes are made storage-independent: in-plane
     axis 0 points toward +x (R), axis 1 toward +y (A), slices ordered inferior -> superior
  4. object masks on both grids, per-channel image sha256, index / frame / patch hashes, registration summary, extractor version
write=True stores $base/unified_engine/patches/ID/<list>_<id>.npz and manifest.csv (the only files written).
Research software: a patch is an input representation, not a finding."""
import csv, json, os
import numpy as np
import nibabel as nib
import pandas as pd
from scipy import ndimage as ndi
from .. import ENGINE_VERSION, provenance as pv
from . import IMAGING_VERSION, index as X
from .geometry import canonical_json

SAP_FILE = os.path.join(pv.SCRIPTS, "surface_aligned_patch.py")
SAP_SHA256 = "ff18972a4fc74e0ecfead9c3fc1dc84e47e4d7fbfec2d4ecfc2af7960aa8508c"
PATCH_SCHEMA = "css-patch/2.0"
SIZE_MM, SPACING_MM = (24.0, 12.0, 8.0), (0.5, 0.5, 0.5)                  # the 1.0 defaults
NATIVE = dict(half_slices=2, crop_mm=32.0, inplane_mm=0.5)
INTENSITY = ("swi", "phase", "flair")
LISTS = (("candidates", "cand_id"), ("excluded", "excl_id"))
MANIFEST_COLS = ["study_id", "list", "obj_id", "cand_uid", "object_key", "detector_version", "status", "skip_reason", "patch_path",
                 "patch_sha", "frame_hash", "channels", "missing_channels", "valid_frac_swi", "native_valid_frac_swi", "native_slices_valid",
                 "normal_flipped", "pial_sd_at_center_mm", "index_sha"]


def _sap():
    if pv.sha256_file(SAP_FILE) != SAP_SHA256: raise pv.ProvenanceError("scripts/surface_aligned_patch.py differs from the pinned sha256")
    return pv.load_legacy("surface_aligned_patch")


def _sha_arrays(arrays):
    import hashlib
    h = hashlib.sha256()
    for k in sorted(arrays):
        a = np.ascontiguousarray(arrays[k]); h.update(k.encode()); h.update(str(a.dtype).encode()); h.update(str(a.shape).encode()); h.update(a.tobytes())
    return h.hexdigest()


def native_axes(A):
    """storage-independent in-plane axes (unit world vectors of array axes 0 / 1, signed toward +x / +y) and the slice step"""
    e = [np.asarray(A[:3, i], float) / np.linalg.norm(A[:3, i]) for i in range(2)]
    ix = 0 if abs(e[0][0]) >= abs(e[1][0]) else 1
    ex, ey = e[ix], e[1 - ix]
    ex = ex if ex[0] >= 0 else -ex; ey = ey if ey[1] >= 0 else -ey
    kstep = 1 if A[2, 2] >= 0 else -1                                   # array axis 2 is S-I (geometry gate)
    return ex, ey, kstep


def native_stack(chans, A, obj_ijk, brain, mask_lab=None, obj_id=None, half=NATIVE["half_slices"], crop=NATIVE["crop_mm"],
                 step=NATIVE["inplane_mm"]):
    """-> dict(arrays, valids, slice_k, world_origin_mm, axes); each slice sampled ON its own acquired plane"""
    ex, ey, kstep = native_axes(A); c = obj_ijk.mean(0); k0 = int(np.round(c[2]))
    ax = (np.arange(int(round(crop / step)) + 1) - int(round(crop / step)) / 2) * step
    a, b = np.meshgrid(ax, ax, indexing="ij")
    Ainv = np.linalg.inv(A); ks = [k0 + kstep * s for s in range(-half, half + 1)]
    arrays, valids, worlds = {}, {}, []
    coords = []
    for k in ks:
        cw = A[:3, :3] @ np.array([c[0], c[1], k]) + A[:3, 3]
        Wp = cw + a[..., None] * ex + b[..., None] * ey; worlds.append(cw)
        V = (Ainv[:3, :3] @ Wp.reshape(-1, 3).T).T + Ainv[:3, 3]; V[:, 2] = k                 # exactly on the acquired slice
        coords.append(V)
    co = np.stack(coords).reshape(len(ks), a.shape[0], a.shape[1], 3)
    shape = next(iter(chans.values())).shape[:3]
    inside = np.all([(co[..., i] >= 0) & (co[..., i] <= shape[i] - 1) for i in range(3)], axis=0)
    flat = np.moveaxis(co.reshape(-1, 3), -1, 0)
    br = ndi.map_coordinates(brain.astype(np.float32), flat, order=0, mode="constant", cval=0).reshape(inside.shape) > 0.5
    for name, img in chans.items():
        order = 0 if name == "labels" else 1
        v = ndi.map_coordinates(np.asarray(img.dataobj, np.float32), flat, order=order, mode="constant", cval=np.nan,
                                prefilter=False).reshape(inside.shape).astype(np.float32)
        ok = inside & np.isfinite(v)
        if name != "labels": ok &= br
        arrays[f"native_{name}"] = np.where(inside, v, np.nan).astype(np.float32); valids[f"native_valid_{name}"] = ok
    if mask_lab is not None:
        mk = ndi.map_coordinates((mask_lab == obj_id).astype(np.float32), flat, order=0, mode="constant", cval=0).reshape(inside.shape) > 0.5
        arrays["native_object_mask"] = mk
    return dict(arrays=arrays, valids=valids, slice_k=ks, world_slice_centres_mm=np.array(worlds),
                axes=dict(ex_world=ex, ey_world=ey, kstep=kstep))


def _objects(base, sid):
    for lst, idc in LISTS:
        mp, cp = os.path.join(base, f"review/{sid}_{lst}.nii.gz"), os.path.join(base, f"review/{sid}_{lst}.csv")
        if os.path.exists(mp) and os.path.exists(cp): yield lst, idc, mp, cp


def extract_study(base, sid, write=False):
    rec = X.index_study(base, sid)                                     # refuses non-synthetic data before any file is opened
    SAP = _sap(); cc = pv.load_legacy("css_common")
    usable = set(rec["usable_channels"]); ch = rec["channels"]
    rows, patches = [], {}
    out_dir = os.path.join(base, "unified_engine", "patches", sid)
    blocked = None
    if rec["status"] not in X.USABLE: blocked = f"study geometry: {rec['status']} ({'; '.join(ch['swi'].get('reasons', []))})"
    elif "pial_sd" not in usable: blocked = f"pial_sd unusable ({ch['pial_sd']['status']}): no surface frame"
    try:
        if blocked is None:
            swi = nib.load(os.path.join(base, ch["swi"]["file"])); psd = nib.load(os.path.join(base, ch["pial_sd"]["file"]))
            chans = {"swi": swi}
            for c in ("phase", "flair", "labels"):
                if c in usable: chans[c] = nib.load(os.path.join(base, ch[c]["file"]))
            missing = {c: ch[c]["status"] for c in ("phase", "flair", "labels") if c not in usable}
            brain = ndi.binary_fill_holes(SAP._arr(swi) > 0)                 # the same brain mask as the 1.0 CLI
        for lst, idc, mp, cp in _objects(base, sid):
            d = pd.read_csv(cp); M_img = None if blocked else nib.load(mp)
            for _, r in d.iterrows():
                oid = int(r[idc]); uid = cc.cand_uid(sid, r); dv = str(r["rule_version"]) if "rule_version" in d.columns else "unknown"
                row = dict(study_id=sid, list=lst, obj_id=oid, cand_uid=uid, object_key=pv.sha256_text(uid + "|" + dv), detector_version=dv,
                           status="skipped", skip_reason="", patch_path="", index_sha=rec["index_sha"])
                if blocked: row["skip_reason"] = blocked; rows.append(row); continue
                try:
                    P = SAP.extract_patch(chans, psd, M_img, SIZE_MM, SPACING_MM, obj_id=oid, labels=chans.get("labels"), brain=brain)
                except ValueError as e:
                    row["skip_reason"] = str(e); rows.append(row); continue
                fr, G = P["frame"], P["grid"]
                arrays = dict(P["arrays"]); valids = dict(P["valids"])
                for name in missing: valids[f"valid_{name}"] = np.zeros(G.shape[:3], bool)
                lab = SAP._arr(M_img)
                om = SAP.sample((lab == oid).astype(np.float32), M_img.affine, G, order=0)[0] > 0.5
                ns = native_stack(chans, swi.affine, np.argwhere(lab == oid), brain, lab, oid)
                for name in missing: ns["valids"][f"native_valid_{name}"] = np.zeros(ns["arrays"]["native_swi"].shape, bool)
                frame_hash = pv.sha256_text(canonical_json({k: np.round(np.asarray(v, float), 6).tolist() for k, v in fr.items()
                                                            if k in ("u_world", "v_world", "n_world", "center_world")}))
                arrs = dict(**arrays, **valids, valid=P["valid"], world_grid_mm=G.astype(np.float32), center_world_mm=fr["center_world"],
                            center_ijk=fr["center_ijk"], u_world=fr["u_world"], v_world=fr["v_world"], n_world=fr["n_world"],
                            object_mask=om, **ns["arrays"], **ns["valids"], native_slice_k=np.array(ns["slice_k"]),
                            native_slice_centres_mm=ns["world_slice_centres_mm"], native_ex_world=ns["axes"]["ex_world"],
                            native_ey_world=ns["axes"]["ey_world"])
                psha = _sha_arrays(arrs)
                meta = dict(schema=PATCH_SCHEMA, extends="css-patch/1.0", subject=sid, list=lst, obj_id=oid, cand_uid=uid, object_key=row["object_key"],
                            detector_version=dv, size_mm=list(SIZE_MM), spacing_mm=list(SPACING_MM),
                            axis_semantics={"0": "u_along_candidate", "1": "v_across_surface", "2": "n_outward"},
                            normal_sign="positive_outward_toward_csf", normal_flipped=bool(fr["normal_flipped"]),
                            pial_sd_at_center_mm=float(fr["pial_sd_at_center_mm"]), channels=sorted(chans), missing_channels=missing,
                            native=dict(NATIVE, axis_semantics={"0": "slice_inferior_to_superior", "1": "inplane_toward_R", "2": "inplane_toward_A"},
                                        through_plane_interpolation=False, slice_k=[int(k) for k in ns["slice_k"]]),
                            interp=dict(intensity="linear", labels="nearest", object_mask="nearest"),
                            image_sha256={c: ch[c]["sha256"] for c in chans}, pial_sd_sha256=ch["pial_sd"]["sha256"],
                            affine_sha=ch["swi"]["header"]["affine_sha"], frame_hash=frame_hash, patch_sha=psha, index_sha=rec["index_sha"],
                            registration={k: v.get("status") for k, v in rec["registration"].items()},
                            channel_status={c: ch[c]["status"] for c in X.CHANNELS}, extractor="scripts/surface_aligned_patch.py",
                            extractor_sha256=SAP_SHA256, imaging_version=IMAGING_VERSION, engine_version=ENGINE_VERSION,
                            synthetic=True, research_only=True)
                arrs["metadata_json"] = json.dumps(meta, sort_keys=True)
                patches[(lst, oid)] = arrs
                row.update(status="ok", patch_sha=psha, frame_hash=frame_hash, channels=";".join(sorted(chans)),
                           missing_channels=";".join(f"{k}:{v}" for k, v in missing.items()),
                           valid_frac_swi=round(float(P["valid"].mean()), 3),
                           native_valid_frac_swi=round(float(ns["valids"]["native_valid_swi"].mean()), 3),
                           native_slices_valid=int(ns["valids"]["native_valid_swi"].any(axis=(1, 2)).sum()),
                           normal_flipped=int(fr["normal_flipped"]), pial_sd_at_center_mm=round(float(fr["pial_sd_at_center_mm"]), 2))
                if write:
                    os.makedirs(out_dir, exist_ok=True); p = os.path.join(out_dir, f"{lst}_{oid}.npz")
                    np.savez_compressed(p, **arrs); row["patch_path"] = os.path.relpath(p, base)
                rows.append(row)
    finally:
        SAP._ARR.clear()                                               # the extractor caches arrays by object id
    if write:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "manifest.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=MANIFEST_COLS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    return dict(study_id=sid, index=rec, rows=rows, patches=patches, blocked=blocked)


def load_patch(path):
    """-> (arrays, metadata); refuses a patch whose arrays no longer match its recorded patch_sha"""
    with np.load(path, allow_pickle=False) as z: arrs = {k: z[k] for k in z.files}
    meta = json.loads(str(arrs.pop("metadata_json")))
    if _sha_arrays(arrs) != meta["patch_sha"]: raise ValueError(f"{path}: arrays do not match patch_sha (edited or corrupted)")
    return arrs, meta
