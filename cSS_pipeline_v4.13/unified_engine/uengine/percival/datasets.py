"""datasets.py (v5.24) - versioned training-dataset manifests. Every training cycle first MATERIALISES its dataset: one JSON manifest with
every labelled candidate, its label and label source, its patient partition and its eligibility per component (eligibility.py). The
manifest is content-hashed: the same reviews, rules and features give the same hash, and an unchanged dataset is not stored twice.
A model records the dataset id it was trained on, so any model can be traced to exactly the examples it learned from.
Feature values and image patches are NOT copied into the manifest (they are re-derived from the study files and cached); the manifest
records the feature schema and the patch specification instead.

v5.24 learning engine (manifest schema percival-dataset/1.1):
  split per example   'test' (locked test patients) or 'train' with a patient-level VALIDATION FOLD 1..K: the patient-grouped
                      cross-validation folds used for model selection (meta.folds on the development patients, same seed) - every
                      development patient is validation in exactly one fold, never in two, and never in the test cohort
  integrity           checked before the manifest is written: no patient in both development and test (leakage), no candidate twice
                      (duplicate), same examination twice -> DUPLICATE_STUDY upstream. A violation raises DatasetError (no dataset).
  reproduce()         rebuilds a manifest's core from the current reviews and reports whether it is identical (same content hash)."""
import glob, hashlib, json, os, time

COMPONENTS = ("char", "image", "fusion", "meta", "predictor", "shadow", "detection", "segmentation")
K_FOLDS, FOLD_SEED = 5, 0                      # = meta.component_oof defaults (patient-grouped CV used for model selection)


class DatasetError(ValueError):
    pass


FEATURE_SCHEMA = "percival-features/1.0"       # MATH (score_v4) + 5 Unified-Score predictors + 9 detector characteristics (meta.CHAR)
PATCH_SPEC = "percival-patch/1.0"              # uengine.imaging.patches candidate patch -> cnn.patch_maps (3 x 7 x 5 block maps)


def _jl(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d

_cid_sort = lambda e: (e["study"], int(e["cand_id"]) if str(e["cand_id"]).isdigit() else 100000 + abs(hash(str(e["cand_id"]))) % 10000)
_cid_val = lambda cid: int(cid) if str(cid).isdigit() else str(cid)


def build(examples, rules_version, store, extra=None):
    """examples: [dict(study, cand_id, patient, y, label_source, reviewer, partition, components {k: ok}, reasons)] (labelled candidates,
    eligible or not). -> manifest (stored as datasets/dsNNN.json unless an identical one exists)"""
    ex = sorted(examples, key=_cid_sort)
    check = verify(ex)
    if check["errors"]: raise DatasetError("dataset integrity: " + "; ".join(check["errors"]))
    folds = assign_folds(ex)
    core = [(e["study"], _cid_val(e["cand_id"]), e.get("patient"), e.get("y"), e.get("label_source"), e.get("partition"),
             sorted(k for k, v in (e.get("components") or {}).items() if v), sorted(e.get("reasons") or [])) for e in ex]
    h = hashlib.sha256(json.dumps([core, rules_version, FEATURE_SCHEMA, PATCH_SPEC], default=str).encode()).hexdigest()[:16]
    d = os.path.join(store, "datasets"); os.makedirs(d, exist_ok=True)
    for p in sorted(glob.glob(os.path.join(d, "ds*.json"))):
        m = _jl(p, {})
        if m.get("content_hash") == h: return m
    comp = {}
    for k in COMPONENTS:
        sel = [e for e in ex if (e.get("components") or {}).get(k)]
        for part in ("development", "test"):
            s = [e for e in sel if e.get("partition") == part]
            comp.setdefault(k, {})[part] = dict(n=len(s), css=sum(1 for e in s if e.get("y") == 1), not_css=sum(1 for e in s if e.get("y") == 0),
                                                patients=len({e.get("patient") for e in s}), studies=len({e["study"] for e in s}))
    excl = {}
    for e in ex:
        if e.get("partition") is None:
            for r in e.get("reasons") or ["?"]: excl[r] = excl.get(r, 0) + 1
    did = f"ds{len(glob.glob(os.path.join(d, 'ds*.json'))) + 1:03d}"
    M = dict(schema="percival-dataset/1.1", id=did, created=time.strftime("%Y-%m-%d %H:%M:%S"), content_hash=h, rules_version=rules_version,
             feature_schema=FEATURE_SCHEMA, patch_spec=PATCH_SPEC, image_preprocessing=PATCH_SPEC, n_examples=len(ex), components=comp, excluded_by_reason=excl,
             integrity=check, splits=dict(method=f"patient-level: locked test by patient hash (meta.test_assignment); development patients in "
                                                 f"{K_FOLDS} patient-grouped validation folds (meta.folds, seed {FOLD_SEED})",
                                          patients=dict(train=len({e.get('patient') for e in ex if e.get('partition') == 'development'}),
                                                        test=len({e.get('patient') for e in ex if e.get('partition') == 'test'})),
                                          folds={str(f): len(v) for f, v in sorted(_inv(folds).items())}),
             label_sources={s: sum(1 for e in ex if e.get("label_source") == s) for s in sorted({e.get("label_source") for e in ex})},
             examples=[dict(study=e["study"], cand_id=_cid_val(e["cand_id"]), patient=e.get("patient"), y=e.get("y"), label_source=e.get("label_source"),
                            reviewer=e.get("reviewer", ""), call=e.get("call"), partition=e.get("partition"),
                            split="test" if e.get("partition") == "test" else "train" if e.get("partition") == "development" else None,
                            validation_fold=folds.get(e.get("patient")) if e.get("partition") == "development" else None,
                            components=e.get("components"), reasons=e.get("reasons"))
                       for e in ex], **(extra or {}))
    with open(os.path.join(d, did + ".json.tmp"), "w") as f: json.dump(M, f, indent=1, default=str)
    os.replace(os.path.join(d, did + ".json.tmp"), os.path.join(d, did + ".json"))
    return M


def listing(store):
    out = []
    for p in sorted(glob.glob(os.path.join(store, "datasets", "ds*.json"))):
        m = _jl(p, {}); out.append({k: v for k, v in m.items() if k != "examples"})
    return out


def load(store, did): return _jl(os.path.join(store, "datasets", f"{did}.json"))


def _inv(folds):
    out = {}
    for p, f in folds.items(): out.setdefault(f, []).append(p)
    return out


def assign_folds(ex):
    """patient -> validation fold 1..K for the development patients of the meta-model (the folds meta.component_oof uses)"""
    from uengine.percival.meta import folds as mfolds
    import numpy as np
    pats = sorted({str(e.get("patient")) for e in ex if e.get("partition") == "development" and (e.get("components") or {}).get("meta")})
    if len(pats) < 2: return {p: 1 for p in pats}
    out = {}
    for i, (_, te) in enumerate(mfolds(np.array(pats), K_FOLDS, FOLD_SEED)):
        for j in te: out[pats[j]] = i + 1
    return out


def verify(ex):
    """integrity of a list of examples: leakage (a patient in development AND test), duplicate candidates -> dict(errors, checks)"""
    dev = {e.get("patient") for e in ex if e.get("partition") == "development"}; tst = {e.get("patient") for e in ex if e.get("partition") == "test"}
    keys = [(e["study"], str(e["cand_id"])) for e in ex]; dup = sorted({k for k in keys if keys.count(k) > 1}) if len(keys) != len(set(keys)) else []
    errors = []
    if dev & tst: errors.append(f"patient leakage: {len(dev & tst)} patient(s) in both development and test")
    if dup: errors.append(f"{len(dup)} candidate(s) listed twice, e.g. {dup[0]}")
    return dict(errors=errors, patients_in_both=len(dev & tst), duplicate_candidates=len(dup), patients_development=len(dev), patients_test=len(tst))


def reproduce(store, did, examples, rules_version):
    """does today's evaluation of the reviews give the same dataset? -> dict(identical, id, stored_hash, rebuilt_hash, differences)"""
    m = load(store, did)
    if not m: return dict(identical=False, error="unknown dataset")
    ex = sorted(examples, key=_cid_sort)
    core = [(e["study"], _cid_val(e["cand_id"]), e.get("patient"), e.get("y"), e.get("label_source"), e.get("partition"),
             sorted(k for k, v in (e.get("components") or {}).items() if v), sorted(e.get("reasons") or [])) for e in ex]
    h = hashlib.sha256(json.dumps([core, rules_version, FEATURE_SCHEMA, PATCH_SPEC], default=str).encode()).hexdigest()[:16]
    key = lambda e: (e.get("y"), e.get("partition"), e.get("label_source"), sorted(k for k, v in (e.get("components") or {}).items() if v), sorted(e.get("reasons") or []))
    old = {(e["study"], str(e["cand_id"])): key(e) for e in m["examples"]}
    new = {(e["study"], str(e["cand_id"])): key(e) for e in ex}
    diff = [dict(study=k[0], cand_id=k[1], stored=old.get(k), now=new.get(k)) for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
    kinds = {}
    for d in diff:
        a, b = d["stored"], d["now"]
        if a is None or b is None: k = "candidate added" if a is None else "candidate no longer labelled"
        elif a[0] != b[0] or a[2] != b[2]: k = "expert label changed"
        elif a[1] != b[1]: k = "partition changed"
        elif a[3] != b[3]: k = "input availability changed (" + ", ".join(sorted(set(a[3]) ^ set(b[3]))) + ")"
        else: k = "eligibility reasons changed"
        d["change"] = k; kinds[k] = kinds.get(k, 0) + 1
    return dict(identical=h == m["content_hash"], id=did, changes=kinds, stored_hash=m["content_hash"], rebuilt_hash=h, rules_version=rules_version,
                stored_rules=m.get("rules_version"), differences=diff[:50], n_differences=len(diff))
