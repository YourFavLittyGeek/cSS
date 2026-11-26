"""synthetic_cohort.py - Stage 2 P3: parametric SYNTHETIC cohort with acquisition variability, mimic subtypes, reader label noise,
indeterminate and insufficient-quality cases, and a negative control (IMAGE_PIPELINE_DESIGN.md section 8).

Everything is invented. The class geometries, contrasts and reader error rates are DESIGN CHOICES for software testing; they are not
measured properties of cSS, of any scanner, or of any reader, and no result on this cohort is a clinical performance estimate.
No clinical image or table is read: the only inputs are a seed and the parameters below. Files are laid out like $CSS_BASE in a base
carrying the synthetic marker (the P1 / P2 code refuses anything else).

sample_profile(rng)          one acquisition profile (vendor phase sign, field, TE, voxel size, SNR, bias, motion ghost, obliquity,
                             storage order, sequence, FLAIR availability / misregistration)
sample_objects(rng, n_css, n_mimic)   object specs: cSS sheets and mimic subtypes, world-defined
render(profile, objects, seed, signal)  arrays on the canonical grid: swi, phase, flair, labels, pial_sd, per-object darkness weight
write_study(base, sid, profile, objects, seed, signal)   files + tables + truth (truth only under unified_engine/image_truth/)
simulate_readers(truth_rows, readers, seed)   css-labels/2.0-shaped reader rows (DATA_SCHEMA section 3)
write_cohort(base, n, seed, signal)          a cohort of SYN001.. studies + cohort.json
signal=0 = NEGATIVE CONTROL: each object is rendered from a kind drawn independently of its label, so images carry no label information."""
import csv, json, os
import numpy as np
import nibabel as nib
from scipy import ndimage as ndi
from . import synthetic_images as S

COHORT_SCHEMA = "uengine-synthetic-cohort/1.0"
LABEL_SCHEMA_V2 = "css-labels/2.0"
SEMI = S.SEMI_AXES_MM

# kind -> (primary_class, mimic_subtype, susceptibility source, contrast range on SWI magnitude (fraction of background kept))
KINDS = {
    "css":                ("definite_css", "", "para", (0.20, 0.40)),
    "vein_surface":       ("definite_mimic", "vein_surface", "para", (0.15, 0.35)),
    "vein_sulcal":        ("definite_mimic", "vein_sulcal", "para", (0.15, 0.35)),
    "vein_transcortical": ("definite_mimic", "vein_transcortical", "para", (0.20, 0.40)),
    "microbleed":         ("definite_mimic", "microbleed", "para", (0.05, 0.20)),
    "calcification":      ("definite_mimic", "calcification", "dia", (0.20, 0.40)),
    "normal_iron_cortex": ("definite_mimic", "normal_iron_cortex", "para", (0.65, 0.80)),
    "artifact_airbone":   ("definite_mimic", "artifact_airbone", "air", (0.05, 0.20)),
}
MIMICS = [k for k in KINDS if k != "css"]
PHASE_AMP_RAD = 0.6
INSUFFICIENT = dict(ghost_min=0.35, snr_max=8.0)        # study-level truth "insufficient_quality" (design choice)

# reader model (design choice): given an ERROR, which wrong kind is called
CONFUSION = {
    "css": {"vein_surface": 0.5, "normal_iron_cortex": 0.3, "artifact_airbone": 0.2},
    "vein_surface": {"css": 0.7, "vein_sulcal": 0.3},
    "vein_sulcal": {"vein_surface": 0.6, "css": 0.4},
    "vein_transcortical": {"vein_surface": 0.5, "microbleed": 0.5},
    "microbleed": {"calcification": 0.6, "vein_transcortical": 0.4},
    "calcification": {"microbleed": 0.9, "css": 0.1},
    "normal_iron_cortex": {"css": 0.8, "vein_surface": 0.2},
    "artifact_airbone": {"css": 0.5, "normal_iron_cortex": 0.5},
}
READERS = {"R1": dict(role="expert", base_error=0.05, base_indet=0.03), "R2": dict(role="trainee", base_error=0.15, base_indet=0.08)}


# ---------------------------------------------------------------- acquisition profiles
def sample_profile(rng, **override):
    field = float(rng.choice([1.5, 3.0], p=[0.3, 0.7]))
    p = dict(vendor=str(rng.choice(["SYNTH-A", "SYNTH-B"])), field_T=field,
             TE_ms=round(float(rng.uniform(30, 45) if field == 1.5 else rng.uniform(15, 30)), 1),
             inplane_mm=round(float(rng.uniform(0.5, 1.0)), 2), slice_mm=round(float(rng.choice([1.0, 1.2, 1.5, 2.0, 2.5, 3.5], p=[.2, .3, .2, .15, .1, .05])), 2),
             snr=round(float(rng.uniform(10, 40) if rng.random() > 0.05 else 6.0), 1), bias=round(float(rng.uniform(0, 0.3)), 3),
             ghost=round(float(rng.choice([0.0, rng.uniform(0.05, 0.2), 0.4], p=[0.8, 0.15, 0.05])), 3),
             tilt_deg=round(float(rng.uniform(0, 15)), 1), axcodes=str(rng.choice(["RAS", "LAS", "LPS"])),
             sequence=str(rng.choice(["SWI", "T2*-GRE"], p=[0.8, 0.2])), flair=bool(rng.random() < 0.85))
    p["flair_shift_mm"] = round(float(rng.choice([0.0, rng.uniform(0.5, 1.5), rng.uniform(2.5, 3.5)], p=[0.85, 0.10, 0.05])), 2)
    p.update(override)
    p["vendor_phase_sign"] = 1 if p["vendor"] == "SYNTH-A" else -1
    p["bloom_mm"] = round(0.4 * (p["TE_ms"] / 20.0) * (p["field_T"] / 3.0), 4)      # blooming radius; design choice
    p["insufficient_quality"] = bool(p["ghost"] >= INSUFFICIENT["ghost_min"] or p["snr"] < INSUFFICIENT["snr_max"])
    return p


# ---------------------------------------------------------------- objects (world-defined)
def _surface_point(k):
    k = S._unit(k); return k / np.sqrt(((k / SEMI) ** 2).sum())


def _direction(rng, kind, used, min_sep_deg=22.0):
    for _ in range(500):
        if kind == "artifact_airbone": k = S._unit([rng.uniform(-0.5, 0.5), rng.uniform(0.3, 0.8), -rng.uniform(0.6, 0.9)])
        else: k = S._unit([rng.normal(), rng.normal(), abs(rng.normal()) + 0.35])
        if all(np.degrees(np.arccos(np.clip(k @ u, -1, 1))) > min_sep_deg for u in used): return k
    raise RuntimeError("could not place objects without overlap - fewer objects needed")


def sample_objects(rng, n_css, n_mimic, mimic_kinds=None):
    kinds = ["css"] * n_css + list(rng.choice(mimic_kinds or MIMICS, size=n_mimic))
    rng.shuffle(kinds); used, out = [], []
    for kind in kinds:
        k = _direction(rng, kind, used); used.append(k)
        t = S._unit(np.cross(k, S._unit(rng.normal(size=3))))
        o = dict(kind=str(kind), direction=k.tolist(), tangent=t.tolist(), contrast=round(float(rng.uniform(*KINDS[kind][3])), 3))
        if kind in ("css", "normal_iron_cortex"):
            o.update(half_angle_deg=round(float(rng.uniform(8, 18)), 2), half_width_mm=round(float(rng.uniform(2.0, 4.5) if kind == "css" else rng.uniform(4, 7)), 2),
                     depth_mm=round(float(rng.uniform(0.8, 1.6) if kind == "css" else rng.uniform(2.4, 2.9)), 2))
        elif kind in ("vein_surface", "vein_sulcal"):
            o.update(half_angle_deg=round(float(rng.uniform(8, 18)), 2), diam_mm=round(float(rng.uniform(0.8, 1.4)), 2))
        elif kind == "vein_transcortical": o.update(radius_mm=round(float(rng.uniform(0.4, 0.7)), 2))
        elif kind == "microbleed": o.update(depth_mm=round(float(rng.uniform(2.0, 5.0)), 2), radius_mm=round(float(rng.uniform(0.8, 1.6)), 2))
        elif kind == "calcification": o.update(depth_mm=round(float(rng.uniform(0.5, 2.5)), 2), radius_mm=round(float(rng.uniform(1.0, 2.0)), 2))
        elif kind == "artifact_airbone":
            o.update(radius_mm=round(float(rng.uniform(4, 8)), 2), lobes=[(rng.normal(size=3) * 2.5).round(2).tolist() for _ in range(3)])
        out.append(o)
    return out


def _predicate(o):
    """-> (predicate over world points, centre, bounding half-size mm) of one rendered kind"""
    kind = o["rendered_kind"]; k = np.asarray(o["direction"]); c = _surface_point(k); R = float(np.linalg.norm(c))
    t = np.asarray(o["tangent"]); w = np.cross(k, t)

    def strip(lo, hi, half_w_mm):
        def f(p):
            d = S.signed_distance(p); q = p / np.linalg.norm(p, axis=-1, keepdims=True)
            return ((q @ k) > np.cos(np.radians(o.get("half_angle_deg", 12)))) & (np.abs(q @ w) < half_w_mm / R) & (d > lo) & (d < hi)
        return f
    ha = np.radians(o.get("half_angle_deg", 12)); span = R * ha + 6
    if kind in ("css", "normal_iron_cortex"): return strip(-o.get("depth_mm", 1.2), 0.0, o.get("half_width_mm", 3.0)), c, span
    if kind == "vein_surface": return strip(0.3, 0.3 + o.get("diam_mm", 1.0), o.get("diam_mm", 1.0) / 2), c, span
    if kind == "vein_sulcal": return strip(1.6, 1.6 + o.get("diam_mm", 1.0), o.get("diam_mm", 1.0) / 2), c, span
    if kind == "vein_transcortical":
        r = o.get("radius_mm", 0.5)
        def f(p):
            along = p @ k; perp = np.linalg.norm(p - along[..., None] * k, axis=-1); d = S.signed_distance(p)
            return (perp < r) & (d > -6.0) & (d < 0.8) & (along > 0)
        return f, c, 10.0
    if kind in ("microbleed", "calcification"):
        cc = c * (1 - o.get("depth_mm", 2.0) / R); r = o.get("radius_mm", 1.0)
        return (lambda p: np.linalg.norm(p - cc, axis=-1) < r), cc, r + 4
    if kind == "artifact_airbone":
        cc = c * (1 - 2.0 / R); r = o.get("radius_mm", 5.0); L = [cc + np.asarray(v) for v in o.get("lobes", [])] or [cc]
        return (lambda p: np.any([np.linalg.norm(p - x, axis=-1) < r * 0.6 for x in L] + [np.linalg.norm(p - cc, axis=-1) < r], axis=0)), cc, r + 8
    raise ValueError(kind)


# ---------------------------------------------------------------- rendering
def _box(A, shape, centre, half_mm):
    v = np.linalg.solve(A[:3, :3], np.asarray(centre) - A[:3, 3]); h = np.abs(np.linalg.solve(A[:3, :3], np.eye(3) * half_mm)).max(1) + 2
    lo = np.clip(np.floor(v - h), 0, np.array(shape) - 1).astype(int); hi = np.clip(np.ceil(v + h) + 1, 1, np.array(shape)).astype(int)
    return tuple(slice(a, b) for a, b in zip(lo, hi))


def occupancy(pred, A, shape, box, ss=2, grow_mm=0.0):
    """partial-volume fraction of each voxel inside the object (ss^3 sub-samples per voxel); grow_mm > 0 grows the object by that
    distance first (geometric blooming), measured on the sub-voxel grid"""
    n = [s.stop - s.start for s in box]
    ax = [s.start + (np.arange(k * ss) + 0.5) / ss - 0.5 for s, k in zip(box, n)]
    F = np.stack(np.meshgrid(*ax, indexing="ij"), -1)
    m = pred(F.reshape(-1, 3) @ A[:3, :3].T + A[:3, 3]).reshape(F.shape[:3])
    if grow_mm > 0 and m.any():
        m = ndi.distance_transform_edt(~m, sampling=np.linalg.norm(A[:3, :3], axis=0) / ss) <= grow_mm
    f = m.reshape(n[0], ss, n[1], ss, n[2], ss).mean(axis=(1, 3, 5))
    out = np.zeros(shape, np.float32); out[box] = f; return out


def render(profile, objects, seed=0, signal=1):
    """-> dict(A, shape, arrays {swi, phase, flair, labels, pial_sd}, weights [per object darkness weight], objects (with rendered_kind))"""
    rng = np.random.default_rng(seed)
    vox = (profile["inplane_mm"], profile["inplane_mm"], profile["slice_mm"])
    A, shape = S.grid_affine(vox, rot_deg=(profile["tilt_deg"], 0, 0))
    ijk = np.indices(shape).reshape(3, -1).T.astype(float); W = (A[:3, :3] @ ijk.T).T + A[:3, 3]
    base = S.phantom(W, "swi").reshape(shape).astype(np.float64)
    brain = base > 0
    objs, weights = [], []
    for o in objects:
        o = dict(o); o["rendered_kind"] = o["kind"] if signal else str(rng.choice(list(KINDS)))
        if not signal:                                  # negative control: geometry AND contrast from the drawn kind, label unchanged
            o = {**sample_objects(np.random.default_rng(rng.integers(1 << 31)), int(o["rendered_kind"] == "css"),
                                  int(o["rendered_kind"] != "css"), [o["rendered_kind"]] if o["rendered_kind"] != "css" else None)[0],
                 "kind": o["kind"], "direction": o["direction"], "tangent": o["tangent"], "rendered_kind": o["rendered_kind"]}
        src = KINDS[o["rendered_kind"]][2]; grow = profile["bloom_mm"] if src in ("para", "dia") else 0.0
        pred, c, half = _predicate(o); box = _box(A, shape, c, half + grow)
        f = occupancy(pred, A, shape, box)
        w = np.maximum(f, 0.85 * occupancy(pred, A, shape, box, grow_mm=grow)) if grow > 0 else f    # blooming: partial signal loss around it
        w = (w * brain).astype(np.float32); weights.append(w); objs.append(o)
    mag = base.copy()
    for o, w in zip(objs, weights): mag *= 1 - (1 - o["contrast"]) * w
    x, y, z = W[:, 0].reshape(shape), W[:, 1].reshape(shape), W[:, 2].reshape(shape)
    bias = 1 + profile["bias"] * (0.6 * x / 40 + 0.3 * y / 45 - 0.4 * z / 32 + 0.3 * (x ** 2 / 1600 - 0.3))
    mag = mag * bias
    if profile["ghost"] > 0: mag = mag + profile["ghost"] * np.roll(mag, shape[1] // 4, axis=1) * brain
    sigma = float(base[brain].mean()) / profile["snr"]
    n1, n2 = rng.normal(0, sigma, shape), rng.normal(0, sigma, shape)
    swi = np.where(brain, np.sqrt((mag + n1) ** 2 + n2 ** 2), 0.0).astype(np.float32)          # Rician magnitude, skull-stripped
    ph = 0.05 * np.sin(x / 13.0) * np.cos(y / 17.0)
    for o, w in zip(objs, weights):
        src = KINDS[o["rendered_kind"]][2]
        if src == "para": ph = ph - profile["vendor_phase_sign"] * PHASE_AMP_RAD * w
        elif src == "dia": ph = ph + profile["vendor_phase_sign"] * PHASE_AMP_RAD * w
        elif src == "air":
            _, c, _ = _predicate(o); ph = ph + PHASE_AMP_RAD * np.sign(z - c[2]) * ndi.gaussian_filter(w, 2.0) * 3
    ph = np.where(brain, ph + rng.normal(0, 1, shape) * sigma / np.maximum(base, 1e-3) * 0.5, 0.0)
    ph = np.angle(np.exp(1j * ph)).astype(np.float32)
    flair = None
    if profile["flair"]:
        Wf = W - np.array([0.0, 0.0, profile["flair_shift_mm"]])
        fl = S.phantom(Wf, "flair").reshape(shape).astype(np.float64) * bias
        flair = (fl + rng.normal(0, float(fl[brain].mean()) / profile["snr"], shape) * (fl > 0)).astype(np.float32)
    return dict(A=A, shape=shape, vox=vox, sigma=sigma, bias_field=bias.astype(np.float32), brain=brain,
                arrays=dict(swi=swi, phase=ph, flair=flair, labels=S.phantom(W, "labels").reshape(shape),
                            pial_sd=S.phantom(W, "pial_sd").reshape(shape)), weights=weights, objects=objs)


def measured_contrast(swi, w, brain, vox):
    """mean SWI inside the object (weight >= 0.5) / mean of a 1-3 mm shell around it (1 = invisible)"""
    m = w >= 0.5
    if not m.any(): return None
    dist = ndi.distance_transform_edt(~m, sampling=vox); shell = (dist > 1.0) & (dist <= 3.0) & brain
    if not shell.any(): return None
    return float(swi[m].mean() / max(swi[shell].mean(), 1e-6))


# ---------------------------------------------------------------- files
def write_study(base, sid, profile, objects, seed=0, signal=1, p_excluded=0.25):
    if not str(sid).startswith("SYN"): raise ValueError("synthetic study codes start with SYN")
    S.guard_base(base)
    for d in ("data", "work", f"raw/{sid}/SWI", "review", "unified_engine/image_truth"): os.makedirs(os.path.join(base, d), exist_ok=True)
    R = render(profile, objects, seed, signal); A = R["A"]; ax = profile["axcodes"]; paths = {}

    def save(ch, data, rel, dtype=None):
        img = S.reorient(S.nifti(np.asarray(data) if dtype is None else np.asarray(data).astype(dtype), A), ax)
        p = os.path.join(base, rel); nib.save(img, p); paths[ch] = p; return img
    swi_img = save("swi", R["arrays"]["swi"], f"data/{sid}_swi.nii")
    save("phase", R["arrays"]["phase"], f"data/{sid}_phase.nii.gz")
    if R["arrays"]["flair"] is not None: save("flair", R["arrays"]["flair"], f"work/{sid}_flair_swispace.nii.gz")
    save("labels", R["arrays"]["labels"], f"work/{sid}_seg_swispace.nii.gz", np.int16)
    save("t1seg", R["arrays"]["labels"], f"work/{sid}_t1seg_swispace.nii.gz", np.int16)
    save("pial_sd", R["arrays"]["pial_sd"], f"work/{sid}_pial_sd.nii.gz")
    geo = (swi_img.affine, swi_img.shape, f"data/{sid}_swi.nii"); t1A, t1s = S.grid_affine((1.0, 1.0, 1.0))
    S.write_lta(os.path.join(base, f"work/{sid}_swi2t1.lta"), S.rigid((1.0, -0.5, 0.8), (1.5, -2.0, 0.7)), src=geo,
                dst=(t1A, t1s, f"subjects/{sid}/mri/orig.mgz"), lta_type=0)
    with open(os.path.join(base, f"work/{sid}_reg.json"), "w") as f: json.dump(dict(method="bbregister", cost=0.45), f)
    if R["arrays"]["flair"] is not None:
        fA, fs = S.grid_affine((0.9, 0.9, 3.0))
        S.write_lta(os.path.join(base, f"work/{sid}_flair2swi.lta"), S.rigid((0.5, 0, -0.7), (-1, 0.5, 2)), src=(fA, fs, "raw/flair.nii.gz"),
                    dst=geo, lta_type=0)
    it = ["ORIGINAL", "PRIMARY", "M"] + (["SWI"] if profile["sequence"] == "SWI" else ["NORM"])
    with open(os.path.join(base, f"raw/{sid}/SWI/{sid}_swi.json"), "w") as f:
        json.dump(dict(Manufacturer=profile["vendor"], MagneticFieldStrength=profile["field_T"], EchoTime=profile["TE_ms"] / 1000,
                       RepetitionTime=0.03, ImageType=it, SliceThickness=profile["slice_mm"], MRAcquisitionType="3D"), f)
    # objects: label map = darkness weight >= 0.5 (what a dark-voxel detector would delineate, blooming included)
    rng = np.random.default_rng(seed + 7); lists = {"candidates": [], "excluded": []}; truth = []
    for i, (o, w) in enumerate(zip(R["objects"], R["weights"])):
        lst = "excluded" if rng.random() < p_excluded else "candidates"; lists[lst].append((i, o, w))
    for lst, idc in (("candidates", "cand_id"), ("excluded", "excl_id")):
        lab = np.zeros(R["shape"], np.int16); ids = {}
        for n, (i, o, w) in enumerate(lists[lst], 1):
            m = (w >= 0.5) & (lab == 0); lab[m] = n; ids[n] = (i, o, w)
        img = save(f"{lst}_mask", lab, f"review/{sid}_{lst}.nii.gz", np.int16); L = np.asarray(img.dataobj); rows = []
        for n, (i, o, w) in ids.items():
            vox_ijk = np.argwhere(L == n); cls, sub, src, _ = KINDS[o["kind"]]
            con = measured_contrast(R["arrays"]["swi"], w, R["brain"], R["vox"])
            t = dict(study_id=sid, list=lst, obj_id=n, kind=o["kind"], rendered_kind=o["rendered_kind"], primary_class=cls, mimic_subtype=sub,
                     n_vox=int(len(vox_ijk)), measured_contrast=None if con is None else round(con, 4), signal=int(signal),
                     quality_truth="insufficient_quality" if profile["insufficient_quality"] else "adequate", rendered=bool(len(vox_ijk)))
            truth.append(t)
            if not len(vox_ijk): continue                                    # partial volume made it invisible: not a detector object
            near = vox_ijk[np.argmin(np.linalg.norm(vox_ijk - vox_ijk.mean(0), axis=1))]
            row = {idc: n, "vox_i": int(near[0]), "vox_j": int(near[1]), "vox_k": int(near[2]),
                   "volume_mm3": round(float(len(vox_ijk) * np.prod(R["vox"])), 3), "rule_version": "SYNTHETIC-P3"}
            if lst == "excluded": row["reason"] = "synthetic"
            rows.append(row); t["cand_uid"] = f"{sid}:{row['vox_i']}:{row['vox_j']}:{row['vox_k']}:{row['volume_mm3']:g}"
        cols = [idc] + (["reason"] if lst == "excluded" else []) + ["vox_i", "vox_j", "vox_k", "volume_mm3", "rule_version"]
        with open(os.path.join(base, f"review/{sid}_{lst}.csv"), "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=cols); wr.writeheader(); wr.writerows(rows)
    tp = os.path.join(base, "unified_engine", "image_truth", f"{sid}.csv")
    cols = ["study_id", "list", "obj_id", "cand_uid", "kind", "rendered_kind", "primary_class", "mimic_subtype", "n_vox", "measured_contrast",
            "signal", "quality_truth", "rendered"]
    with open(tp, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); wr.writeheader(); wr.writerows(truth)
    return dict(paths=paths, truth=truth, profile=profile, render=R)


# ---------------------------------------------------------------- readers
def difficulty(t, profile):
    """0 (easy) .. 1 (hard): low measured contrast-to-noise, small objects, confusable kinds (design choice)"""
    con = t.get("measured_contrast"); cnr = 0.0 if con is None else max(0.0, (1 - con)) * profile["snr"]
    size = min(1.0, t.get("n_vox", 0) / 30.0)
    confusable = 0.25 if t["kind"] in ("normal_iron_cortex", "vein_surface", "calcification") else 0.0
    return float(np.clip(1 / (1 + cnr / 4.0) * (1 - 0.4 * size) + confusable, 0, 1))


def simulate_readers(truth, profiles, readers=READERS, seed=0):
    rng = np.random.default_rng(seed); out = []
    for t in truth:
        if not t.get("rendered", True) or not t.get("cand_uid"): continue
        prof = profiles[t["study_id"]]; dif = difficulty(t, prof)
        for rid, rd in readers.items():
            row = dict(study_id=t["study_id"], patient_key=t["study_id"], reader_id=rid, reader_role=rd["role"], session=1, blinded=1,
                       list=t["list"], obj_id=t["obj_id"], cand_uid=t["cand_uid"], detector_version="SYNTHETIC-P3", mimic_subtype="",
                       quality_reason="", scope_reason="", timestamp="SYNTHETIC", label_schema_version=LABEL_SCHEMA_V2)
            u = rng.random()
            if prof["insufficient_quality"] and u < 0.85:
                row.update(primary_class="insufficient_quality", quality_reason="motion" if prof["ghost"] >= INSUFFICIENT["ghost_min"] else "noise",
                           confidence=4)
            elif u < rd["base_indet"] + 0.5 * dif:
                row.update(primary_class="indeterminate", confidence=2)
            elif rng.random() < rd["base_error"] + 0.4 * dif:
                c = CONFUSION[t["kind"]]; wrong = str(rng.choice(list(c), p=list(c.values())))
                row.update(primary_class=KINDS[wrong][0], mimic_subtype=KINDS[wrong][1], confidence=int(rng.choice([2, 3, 4])))
            else:
                row.update(primary_class=t["primary_class"], mimic_subtype=t["mimic_subtype"], confidence=5 if dif < 0.3 else 4)
            row["difficulty"] = round(dif, 3); out.append(row)
    return out


READER_COLS = ["study_id", "patient_key", "reader_id", "reader_role", "session", "blinded", "list", "obj_id", "cand_uid", "detector_version",
               "primary_class", "mimic_subtype", "confidence", "quality_reason", "scope_reason", "timestamp", "label_schema_version", "difficulty"]


# ---------------------------------------------------------------- cohort
def write_cohort(base, n=8, seed=0, signal=1, p_positive=0.6, profile_override=None):
    rng = np.random.default_rng(seed); profiles, truth = {}, []
    for s in range(n):
        sid = f"SYN{s + 1:03d}"; prof = sample_profile(rng, **(profile_override or {}))
        pos = rng.random() < p_positive
        objs = sample_objects(rng, int(rng.integers(1, 4)) if pos else 0, int(rng.integers(3, 6)))
        r = write_study(base, sid, prof, objs, seed=int(rng.integers(1 << 31)), signal=signal)
        profiles[sid] = prof; truth += r["truth"]
    readers = simulate_readers(truth, profiles, seed=seed + 1)
    with open(os.path.join(base, "unified_engine", "image_truth", "readers.csv"), "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=READER_COLS); wr.writeheader(); wr.writerows(readers)
    meta = dict(schema=COHORT_SCHEMA, seed=seed, n=n, signal=signal, p_positive=p_positive, profiles=profiles, kinds=list(KINDS),
                readers=READERS, confusion=CONFUSION, insufficient=INSUFFICIENT, synthetic=True,
                note="invented parameters for software testing; not clinical, scanner or reader estimates")
    with open(os.path.join(base, "unified_engine", "image_truth", "cohort.json"), "w") as f: json.dump(meta, f, indent=1)
    return dict(profiles=profiles, truth=truth, readers=readers, meta=meta)


# ---------------------------------------------------------------- P1 threshold re-check
def shift_recheck(profiles, shifts_mm, seed=0, axis=2):
    """residual-shift classification of a FLAIR shifted by known amounts, on each profile's grid (no files written)"""
    from . import registration as RG
    rows = []
    for pid, prof in profiles.items():
        p = dict(prof, flair=True, flair_shift_mm=0.0, ghost=min(prof["ghost"], 0.2))
        for s in shifts_mm:
            p["flair_shift_mm"] = float(s)
            R = render(p, [], seed=seed)
            r = RG.residual_shift(R["arrays"]["swi"], R["arrays"]["flair"], R["vox"], R["A"])
            rows.append(dict(profile=pid, slice_mm=prof["slice_mm"], inplane_mm=prof["inplane_mm"], snr=prof["snr"], bias=prof["bias"],
                             true_shift_mm=float(s), est_shift_mm=r.get("shift_mm"), status=r["status"]))
    return rows
