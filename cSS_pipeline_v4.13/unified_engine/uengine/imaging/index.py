"""index.py - ImageRecord index of one SYNTHETIC study (Stage 2 P1; DATA_SCHEMA.md section 2).

index_study(base, sid, write=False) -> dict (schema css-image-index/1.0)
  - refuses (NotSynthetic) BEFORE opening any file unless the base carries the synthetic marker AND the study code starts with SYN
  - per channel (swi, phase, flair, labels, pial_sd): file, sha256, size, mtime, header description, and a channel status
      ok | missing | stale | off_grid | geometry_refused | quality_refused | low_confidence | misregistered | registration_invalid
    the SWI gets the full geometry gate; the others must be on the SWI grid and not older than the SWI (never resampled, never
    zero-filled); FLAIR also gets the image-based residual-shift check; channels resampled through an LTA inherit that LTA's state
  - registration chain (swi2t1, flair2swi, reg.json), anatomy source, acquisition (css_qc.read_acq), existing review/ID_qc.json summary
  - study status = the SWI gate status; usable_channels = channels with status ok or low_confidence
  - every input file is hashed before and after; `inputs_unchanged` records the comparison
write=True stores the record at $base/unified_engine/image_index/ID.json (the only file this module writes)."""
import datetime, json, os
import nibabel as nib
import numpy as np
from .. import ENGINE_VERSION, provenance as pv
from ..demo_base import is_synthetic_base
from . import IMAGING_VERSION, INDEX_SCHEMA, NotSynthetic, verify_sources
from . import geometry as G, registration as RG

CHANNELS = {"swi": "data/{sid}_swi.nii", "phase": "data/{sid}_phase.nii.gz", "flair": "work/{sid}_flair_swispace.nii.gz",
            "labels": "work/{sid}_seg_swispace.nii.gz", "pial_sd": "work/{sid}_pial_sd.nii.gz"}
REG = {"swi2t1": ("work/{sid}_swi2t1.lta", "src"), "flair2swi": ("work/{sid}_flair2swi.lta", "dst")}
EXTRA = ["work/{sid}_t1seg_swispace.nii.gz", "work/{sid}_a2009s_swispace.nii.gz", "work/{sid}_reg.json", "review/{sid}_qc.json"]
USABLE = ("ok", "low_confidence")
QC_KEYS = ("status", "orientation_ok", "obliquity_deg", "anatomy", "edge_agreement_mm", "label_shift_mm")


def local_learning_authorized(base):
    """v5.21: the user authorised LOCAL learning on this project's MRI in the app (app_data/ml_authorization.json, written only by the
    app's Model screen). Everything stays on this computer."""
    try:
        with open(os.path.join(base, "app_data", "ml_authorization.json")) as f: return bool(json.load(f).get("local_learning"))
    except Exception: return False


def is_synthetic_study(base, sid): return is_synthetic_base(base) and str(sid).startswith("SYN")


def require_synthetic(base, sid):
    if is_synthetic_study(base, sid) or local_learning_authorized(base): return
    if not is_synthetic_base(base): raise NotSynthetic(f"{base} is not a synthetic base (no marker) - Stage 2 P1 indexes synthetic data only (local learning not authorised)")
    raise NotSynthetic(f"study {sid!r} is not a synthetic study code (SYN...)")


def _inputs(base, sid):
    rels = [t.format(sid=sid) for t in CHANNELS.values()] + [t.format(sid=sid) for t, _ in REG.values()] + [t.format(sid=sid) for t in EXTRA]
    swi_json = os.path.join(base, "raw", sid, "SWI")
    if os.path.isdir(swi_json): rels += [os.path.join("raw", sid, "SWI", f) for f in sorted(os.listdir(swi_json))]
    return {r: pv.sha256_file(os.path.join(base, r)) for r in rels if os.path.isfile(os.path.join(base, r))}


def _channel(base, sid, ch, swi_d, swi_path):
    rel = CHANNELS[ch].format(sid=sid); p = os.path.join(base, rel)
    if not os.path.exists(p): return dict(file=rel, status="missing", reasons=["file not found"]), None
    img = nib.load(p); d = G.describe(img)
    r = dict(file=rel, sha256=pv.sha256_file(p), size=os.path.getsize(p), mtime=os.path.getmtime(p), header=d, reasons=[])
    if ch == "swi":
        g = G.gate(d); r["gate"] = g; r["status"] = g["status"]; r["reasons"] = g["reasons"]; return r, img
    if swi_d is None:
        r.update(status="geometry_refused", reasons=["the SWI is unusable"]); return r, img
    r["on_swi_grid"] = G.same_grid(d, swi_d); r["fresh"] = os.path.getmtime(p) >= os.path.getmtime(swi_path)
    if not r["on_swi_grid"]: r.update(status="off_grid", reasons=["not on the SWI grid (shape / affine): not resampled here"])
    elif not r["fresh"]: r.update(status="stale", reasons=["older than the SWI"])
    else: r["status"] = "ok"
    return r, img


def index_study(base, sid, write=False):
    require_synthetic(base, sid)
    before = _inputs(base, sid)
    rec = dict(schema=INDEX_SCHEMA, imaging_version=IMAGING_VERSION, engine_version=ENGINE_VERSION, study_id=sid, synthetic=is_synthetic_study(base, sid),
               created=datetime.datetime.now().isoformat(timespec="seconds"), pinned_sources_problems=verify_sources(),
               thresholds=dict(max_inplane_mm=G.MAX_INPLANE_MM, max_slice_mm=G.MAX_SLICE_MM, thick_slice_mm=G.THICK_SLICE_MM,
                               oblique_low_conf_deg=G.OBLIQUE_LOW_CONF_DEG, reg_cost_low_conf=RG.REG_COST_LOW_CONF,
                               shift_ok_mm=RG.SHIFT_OK_MM, shift_refuse_mm=RG.SHIFT_REFUSE_MM, grid_tol_mm=G.GRID_TOL_MM))
    swi_path = os.path.join(base, CHANNELS["swi"].format(sid=sid))
    ch, imgs = {}, {}
    ch["swi"], imgs["swi"] = _channel(base, sid, "swi", None, swi_path)
    swi_ok = ch["swi"]["status"] in USABLE
    swi_d = ch["swi"]["header"] if swi_ok else None
    for c in ("phase", "flair", "labels", "pial_sd"): ch[c], imgs[c] = _channel(base, sid, c, swi_d, swi_path)
    reg = {}
    if "header" in ch["swi"]:
        for k, (t, role) in REG.items(): reg[k] = RG.lta_record(os.path.join(base, t.format(sid=sid)), base, ch["swi"]["header"], swi_path, role)
    reg["reg_json"] = RG.reg_json(os.path.join(base, f"work/{sid}_reg.json"), base)
    t1 = os.path.join(base, f"work/{sid}_t1seg_swispace.nii.gz")
    t1_anat = os.path.exists(t1) and os.path.exists(swi_path) and os.path.getmtime(t1) >= os.path.getmtime(swi_path)
    anatomy = ("T1 recon-all" if t1_anat and os.path.exists(os.path.join(base, f"work/{sid}_a2009s_swispace.nii.gz"))
               else ("T1" if t1_anat else "SWI-only"))          # the same rule as css_qc.case_qc
    # channels that were resampled onto the SWI grid through an LTA inherit its state
    deps = {"flair": ["flair2swi"], "labels": ["swi2t1"] if anatomy.startswith("T1") else []}
    for c, ks in deps.items():
        if ch[c]["status"] not in USABLE: continue
        for k in ks:
            st = reg.get(k, {}).get("status")
            if st in ("invalid", "missing"):
                ch[c]["status"] = "registration_invalid"; ch[c]["reasons"].append(f"{k}: {st} ({'; '.join(reg[k].get('reasons', []))})")
            elif st == "stale" and ch[c]["status"] == "ok":
                ch[c]["status"] = "stale"; ch[c]["reasons"].append(f"{k} is older than the SWI")
            if k == "swi2t1" and reg["reg_json"].get("cost_above_threshold") and ch[c]["status"] == "ok":
                ch[c]["status"] = "low_confidence"; ch[c]["reasons"].append(f"registration cost {reg['reg_json']['cost']} > {RG.REG_COST_LOW_CONF}")
    if ch["flair"]["status"] in USABLE:
        sh = RG.residual_shift(np.asanyarray(imgs["swi"].dataobj), np.asanyarray(imgs["flair"].dataobj), ch["swi"]["header"]["zooms_mm"],
                               imgs["swi"].affine)
        ch["flair"]["residual_shift"] = sh
        if sh["status"] == "misregistered": ch["flair"]["status"] = "misregistered"; ch["flair"]["reasons"] += sh["reasons"]
        elif sh["status"] in ("low_confidence", "unmeasurable") and ch["flair"]["status"] == "ok":
            ch["flair"]["status"] = "low_confidence"; ch["flair"]["reasons"] += sh["reasons"]
    qc_p = os.path.join(base, f"review/{sid}_qc.json"); qc = None
    if os.path.exists(qc_p):
        with open(qc_p) as f: q = json.load(f)
        qc = {k: q.get(k) for k in QC_KEYS}
    rec.update(status=ch["swi"]["status"] if "header" in ch["swi"] else "missing", channels=ch, registration=reg, anatomy_source=anatomy,
               acquisition=RG.read_acquisition(base, sid), css_qc=qc,
               usable_channels=[c for c in CHANNELS if ch[c]["status"] in USABLE] if swi_ok else [])
    after = _inputs(base, sid)
    rec["inputs_sha256"] = before; rec["inputs_unchanged"] = before == after
    rec["index_sha"] = record_sha(rec)
    if write:
        d = os.path.join(base, "unified_engine", "image_index"); os.makedirs(d, exist_ok=True)
        p = os.path.join(d, f"{sid}.json"); tmp = p + ".tmp"
        with open(tmp, "w") as f: json.dump(rec, f, indent=1, default=float)
        os.replace(tmp, p); rec["path"] = p
    return rec


def record_sha(rec):
    """content hash of a record without its volatile fields (creation time, file mtimes, its own hash / path)"""
    def strip(o):
        if isinstance(o, dict): return {k: strip(v) for k, v in o.items() if k not in ("created", "mtime", "index_sha", "path")}
        if isinstance(o, list): return [strip(v) for v in o]
        return o
    return pv.sha256_text(G.canonical_json(strip(rec)))


def verify_index(path):
    """-> (ok, reason): the stored record still matches its own hash"""
    with open(path) as f: rec = json.load(f)
    ok = rec.get("index_sha") == record_sha(rec)
    return ok, "ok" if ok else "content does not match index_sha (edited or corrupted)"
