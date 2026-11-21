"""image_infer.py - local Image ML inference for one SYNTHETIC study (Stage 2 prototype). No network; numpy / scipy only.

run_study(base, sid, model_path=None, write=False) -> result dict (schema css-image-ml/1.0)
  - P1 index + P2 patches (non-synthetic data refused before any file is opened)
  - model: the given file, else the newest healthy model in $base/unified_engine/models/image/ then the bundled models/image/;
    a synthetic-trained model is applied only to synthetic studies (data_kind policy)
  - per object: status ok / no_patch (with the extractor's reason) / not_scorable (study geometry, no surface frame) / model_unavailable;
    for ok: predicted class, class probabilities, p(cSS) with 5-95 % interval, confidence, category, quality flags, features, coordinates
    (stored voxel fingerprint, world centre), small patch previews for display
  - every input file (images, detector tables) is hashed before and after: original_inputs_unchanged
  - CSS_IMAGE_ENGINE_FAIL=1 simulates a model crash (tests): raises, nothing is written
write=True stores $base/unified_engine/image_ml/ID.json (+ the P2 patch files). Nothing else is written."""
import csv, glob, json, os
import numpy as np
from .. import ENGINE_VERSION, SYNTHETIC_STAMP, provenance as pv
from . import IMAGING_VERSION, image_model as IM, index as X, patches as PT

RESULT_SCHEMA = "css-image-ml/1.0"
BUNDLED = os.path.join(pv.ENGINE, "models", "image")


def model_paths(base=None):
    dirs = ([os.path.join(base, "unified_engine", "models", "image")] if base else []) + [BUNDLED]
    return [p for d in dirs for p in sorted(glob.glob(os.path.join(d, "*.json")))]


def list_models(base=None, cards=False):
    out = []
    for p in model_paths(base):
        h = IM.health(p)
        if not cards: h.pop("card", None)
        else:
            c = h.get("card") or {}; h["card"] = {k: c.get(k) for k in ("name", "version", "created", "data_kind", "classes", "n_features", "method", "training", "evaluation",
                                                                        "intended_use", "out_of_scope")}
        h["file_size"] = os.path.getsize(p) if os.path.exists(p) else 0; out.append(h)
    return out


def select_model(base, model_path=None):
    if model_path: return model_path, IM.health(model_path)
    cands = [(p, IM.health(p)) for p in model_paths(base)]
    ok = [(p, h) for p, h in cands if h["status"] == "ok"]
    if not ok: return None, dict(status="missing", reasons=["no healthy image model found"] + [f"{os.path.basename(p)}: {h['status']}" for p, h in cands])
    return max(ok, key=lambda ph: (ph[1]["card"].get("created", ""), ph[0]))


def _preview(img, valid, mask, lo=0.0, hi=1.5):
    ref = float(np.median(img[valid])) if valid.any() else 1.0
    z = np.where(valid, img / (ref if ref > 0 else 1.0), np.nan)
    g = np.where(np.isfinite(z), np.clip((z - lo) / (hi - lo), 0, 1) * 255, 0).astype(int)
    return dict(gray=g.tolist(), mask=mask.astype(int).tolist(), valid=valid.astype(int).tolist())


def previews(a):
    cn = a["image_swi"].shape[2] // 2; cu = a["image_swi"].shape[0] // 2
    return dict(surface_uv=_preview(a["image_swi"][:, :, cn].T, a["valid_swi"][:, :, cn].T, a["object_mask"][:, :, cn].T),
                surface_vn=_preview(a["image_swi"][cu].T[::-1], a["valid_swi"][cu].T[::-1], a["object_mask"][cu].T[::-1]),
                native_centre=_preview(a["native_swi"][2].T[::-1], a["native_valid_swi"][2].T[::-1], a["native_object_mask"][2].T[::-1]),
                axes=dict(surface_uv="x: along candidate (u), y: across surface (v); slice n = 0",
                          surface_vn="x: across surface (v), y: outward normal (n, up = toward CSF)",
                          native_centre="acquired axial slice; x: toward R, y: toward A (up)"))


def _hash_inputs(base, sid):
    pats = [f"data/{sid}_*", f"work/{sid}_*", f"review/{sid}_*", f"raw/{sid}/SWI/*"]
    return {os.path.relpath(p, base): pv.sha256_file(p) for g in pats for p in sorted(glob.glob(os.path.join(base, g))) if os.path.isfile(p)}


def _coords(base, sid):
    out = {}
    for lst, idc in PT.LISTS:
        p = os.path.join(base, "review", f"{sid}_{lst}.csv")
        if not os.path.exists(p): continue
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                out[(lst, int(r[idc]))] = dict(vox_ijk=[int(r["vox_i"]), int(r["vox_j"]), int(r["vox_k"])], volume_mm3=float(r["volume_mm3"]))
    return out


def run_study(base, sid, model_path=None, write=False):
    X.require_synthetic(base, sid)
    before = _hash_inputs(base, sid)
    mpath, mh = select_model(base, model_path)
    model = None; model_reason = ""
    if mh.get("status") == "ok":
        if mh.get("data_kind") != "synthetic": model_reason = f"model data_kind {mh.get('data_kind')!r}: only synthetic models exist in this prototype"
        else: model, mh = IM.load(mpath)
    else: model_reason = f"{mh.get('status')}: {'; '.join(mh.get('reasons', []))}"
    E = PT.extract_study(base, sid, write=write)
    coords = _coords(base, sid); ok_keys = [k for k, a in E["patches"].items()]
    sign, sign_ok = IM.study_phase_sign([E["patches"][k] for k in ok_keys])
    feats = {k: IM.patch_features(E["patches"][k], json.loads(E["patches"][k]["metadata_json"]), sign) for k in ok_keys}
    preds = {}
    if model is not None and os.environ.get("CSS_IMAGE_ENGINE_FAIL") == "1":
        raise RuntimeError("simulated image model failure (CSS_IMAGE_ENGINE_FAIL=1)")
    if model is not None and ok_keys:
        st = E["index"]["status"]; flags = []
        for k in ok_keys:
            f = []
            if feats[k]["valid_frac"] < IM.QUALITY_MIN_VALID: f.append(f"patch valid fraction {feats[k]['valid_frac']:.2f} < {IM.QUALITY_MIN_VALID}")
            miss = [c for c in ("phase", "flair", "labels") if feats[k][f"{c}_missing"] == 1.0]
            if len(miss) >= 2: f.append(f"channels missing: {', '.join(miss)}")
            if st == "low_confidence": f.append("study geometry low confidence: " + "; ".join(E["index"]["channels"]["swi"].get("reasons", [])))
            if not sign_ok: f.append("phase sign could not be established for this study")
            flags.append(f)
        for k, p in zip(ok_keys, model.predict(IM.matrix([feats[k] for k in ok_keys]), flags)): preds[k] = p
    cands = []
    for r in E["rows"]:
        k = (r["list"], int(r["obj_id"])); a = E["patches"].get(k)
        c = dict(list=r["list"], obj_id=r["obj_id"], ref=f"{'c' if r['list'] == 'candidates' else 'x'}{r['obj_id']}", cand_uid=r["cand_uid"],
                 object_key=r["object_key"], **coords.get(k, {}))
        if a is not None: c["world_centre_mm"] = np.round(a["center_world_mm"], 2).tolist()
        if r["status"] != "ok":
            c.update(status="not_scorable" if E["blocked"] else "no_patch", reason=r["skip_reason"])
        elif model is None: c.update(status="model_unavailable", reason=model_reason)
        else:
            c.update(status="ok", **preds[k], features={n: (None if not np.isfinite(v) else round(float(v), 4)) for n, v in feats[k].items()},
                     patch_sha=r["patch_sha"], patch_path=r.get("patch_path", ""))
        if a is not None: c["previews"] = previews(a)
        cands.append(c)
    counts = {}
    for c in cands: counts[c.get("category", c["status"])] = counts.get(c.get("category", c["status"]), 0) + 1
    after = _hash_inputs(base, sid)
    card = (mh.get("card") or {}) if model is not None else {}
    res = dict(schema=RESULT_SCHEMA, study_id=sid, created=IM.now(), synthetic=True, experimental=True, stamp=SYNTHETIC_STAMP,
               engine_version=ENGINE_VERSION, imaging_version=IMAGING_VERSION,
               study=dict(index_status=E["index"]["status"], index_sha=E["index"]["index_sha"], usable_channels=E["index"]["usable_channels"],
                          blocked=E["blocked"], swi_reasons=E["index"]["channels"]["swi"].get("reasons", []),
                          channel_status={c: v["status"] for c, v in E["index"]["channels"].items()}, phase_sign=sign, phase_sign_established=sign_ok),
               model=dict(applied=model is not None, path=os.path.relpath(mpath, pv.ENGINE) if mpath and mpath.startswith(pv.ENGINE) else mpath,
                          status=mh.get("status"), reason=model_reason, name=card.get("name"), version=card.get("version"),
                          data_kind=card.get("data_kind"), model_hash=mh.get("model_hash"), created=card.get("created"),
                          classes=card.get("classes"), features=IM.FEATURES, training=card.get("training"), evaluation=card.get("evaluation"),
                          intended_use=card.get("intended_use")),
               candidates=cands, category_counts=counts, original_inputs_unchanged=before == after)
    if write:
        d = os.path.join(base, "unified_engine", "image_ml"); os.makedirs(d, exist_ok=True); p = os.path.join(d, f"{sid}.json")
        with open(p + ".tmp", "w") as f: json.dump(res, f, default=float)
        os.replace(p + ".tmp", p); res["path"] = p
    return res
