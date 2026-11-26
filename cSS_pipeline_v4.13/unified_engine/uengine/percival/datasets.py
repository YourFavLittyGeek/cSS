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

COMPONENTS = ("char", "image", "meta", "shadow", "detection", "segmentation")
K_FOLDS, FOLD_SEED = 5, 0                      # = meta.component_oof defaults (patient-grouped CV used for model selection)


class DatasetError(ValueError):
    pass


FEATURE_SCHEMA = "percival-features/1.0"       # MATH (score_v4) + 5 Unified-Score predictors + 9 detector characteristics (meta.CHAR)
PATCH_SPEC = "percival-patch/1.0"              # uengine.imaging.patches candidate patch -> cnn.patch_maps (3 x 7 x 5 block maps)


def _jl(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d

_cid_sort = lambda e: (str(e["study"]), 0, int(e["cand_id"]), "") if str(e["cand_id"]).isdigit() else (str(e["study"]), 1, 0, str(e["cand_id"]))   # 3C: deterministic (no hash())
_cid_val = lambda cid: int(cid) if str(cid).isdigit() else str(cid)


ELIGIBLE_CLASSES = ("verified_blind_post_3A", "historical_blinding_verified")   # = call_ledger.PRIMARY_ELIGIBLE (Phase 3A/3B policy)
EXPERT_SOURCES = ("review", "expert_missed_lesion")


def _core(e):
    return (e["study"], _cid_val(e["cand_id"]), e.get("patient"), e.get("y"), e.get("label_source"), e.get("partition"),
            sorted(k for k, v in (e.get("components") or {}).items() if v), sorted(e.get("reasons") or []), e.get("gt_class"), e.get("gt_status"))


def content_hash(ex, rules_version, sources=None, split=None):
    """3C: identical examples + rules + schemas + source-file hashes + split version -> identical hash (timestamps excluded)"""
    return hashlib.sha256(json.dumps([[_core(e) for e in ex], rules_version, FEATURE_SCHEMA, PATCH_SPEC, sources or {}, split or {}],
                                     default=str, sort_keys=True).encode()).hexdigest()[:16]


def readiness(ex):
    """3C/3D: every example used for training must be eligible EXPERT ground truth -> [problem] (empty = ready)"""
    out = []
    for e in ex:
        if e.get("partition") not in ("development", "test"): continue
        if e.get("label_source") not in EXPERT_SOURCES: out.append(f"{e['study']}#{e['cand_id']}: label source {e.get('label_source')} is not expert review")
        if e.get("gt_class") not in ELIGIBLE_CLASSES: out.append(f"{e['study']}#{e['cand_id']}: provenance {e.get('gt_class')} not eligible")
        if e.get("y") not in (0, 1): out.append(f"{e['study']}#{e['cand_id']}: no binary expert label")
    return out


def build(examples, rules_version, store, extra=None, sources=None, split=None):
    """examples: [dict(study, cand_id, patient, y, label_source, reviewer, partition, components {k: ok}, reasons, gt_class, gt_status)]
    (labelled candidates, eligible or not). sources: {study: file hashes}; split: dict(version, assignment_sha256).
    -> manifest (stored as datasets/dsNNN.json unless an identical one exists)"""
    ex = sorted(examples, key=_cid_sort)
    check = verify(ex)
    if check["errors"]: raise DatasetError("dataset integrity: " + "; ".join(check["errors"]))
    folds = assign_folds(ex)
    h = content_hash(ex, rules_version, sources, split)
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
    M = dict(schema="percival-dataset/1.2", id=did, created=time.strftime("%Y-%m-%d %H:%M:%S"), content_hash=h, rules_version=rules_version,
             sources=sources or {}, split=split or {}, readiness_problems=readiness(ex),
             provenance={c: sum(1 for e in ex if e.get("gt_class") == c and e.get("partition")) for c in sorted({str(e.get("gt_class")) for e in ex})},
             feature_schema=FEATURE_SCHEMA, patch_spec=PATCH_SPEC, image_preprocessing=PATCH_SPEC, n_examples=len(ex), components=comp, excluded_by_reason=excl,
             integrity=check, splits=dict(method=f"patient-level: locked test by patient hash (meta.test_assignment); development patients in "
                                                 f"{K_FOLDS} patient-grouped validation folds (meta.folds, seed {FOLD_SEED})",
                                          patients=dict(train=len({e.get('patient') for e in ex if e.get('partition') == 'development'}),
                                                        test=len({e.get('patient') for e in ex if e.get('partition') == 'test'})),
                                          folds={str(f): len(v) for f, v in sorted(_inv(folds).items())}),
             label_sources={s: sum(1 for e in ex if e.get("label_source") == s) for s in sorted({e.get("label_source") for e in ex})},
             examples=[dict(study=e["study"], cand_id=_cid_val(e["cand_id"]), patient=e.get("patient"), y=e.get("y"), label_source=e.get("label_source"),
                            reviewer=e.get("reviewer", ""), call=e.get("call"), partition=e.get("partition"), gt_class=e.get("gt_class"), gt_status=e.get("gt_status"),
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


def reproduce(store, did, examples, rules_version, sources=None):
    """does today's evaluation of the reviews give the same dataset? -> dict(identical, id, stored_hash, rebuilt_hash, differences)
    sources: TODAY's source-file hashes (3C) - a changed input file makes the rebuilt hash differ (reported as 'source files changed')"""
    m = load(store, did)
    if not m: return dict(identical=False, error="unknown dataset")
    ex = sorted(examples, key=_cid_sort)
    cur_src = m.get("sources") if sources is None else {k: v for k, v in sources.items() if k in (m.get("sources") or sources)}
    h = content_hash(ex, rules_version, cur_src, m.get("split"))
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


def export(store, did, out_dir):
    """3C: a plain export of one dataset version for the training pipeline and for review: examples.csv (one row per labelled candidate:
    study, candidate, protected patient id, label, partition, validation fold, label source, provenance class, consensus status, reviewer),
    manifest.json (the stored manifest, unchanged), split.json (the split version it used) and SHA256SUMS. Nothing else is written."""
    import csv, shutil
    m = load(store, did)
    if not m: raise DatasetError(f"unknown dataset {did}")
    os.makedirs(out_dir, exist_ok=False)
    cols = ["study", "cand_id", "patient", "y", "partition", "split", "validation_fold", "label_source", "gt_class", "gt_status", "reviewer", "call"]
    with open(os.path.join(out_dir, "examples.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for e in m["examples"]: w.writerow([e.get(c, "") if e.get(c) is not None else "" for c in cols])
    shutil.copy2(os.path.join(store, "datasets", f"{did}.json"), os.path.join(out_dir, "manifest.json"))
    sv = (m.get("split") or {}).get("version")
    if sv and os.path.exists(os.path.join(store, "split", f"{sv}.json")): shutil.copy2(os.path.join(store, "split", f"{sv}.json"), os.path.join(out_dir, "split.json"))
    with open(os.path.join(out_dir, "SHA256SUMS"), "w") as f:
        for n in sorted(os.listdir(out_dir)):
            if n != "SHA256SUMS": f.write(hashlib.sha256(open(os.path.join(out_dir, n), "rb").read()).hexdigest() + "  " + n + "\n")
    return dict(ok=True, out=out_dir, files=sorted(os.listdir(out_dir)), dataset=did, content_hash=m["content_hash"])
