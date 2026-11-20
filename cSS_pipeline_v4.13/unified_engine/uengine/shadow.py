"""shadow.py - SHADOW MODE runner: computes the experimental Unified Score for one study NEXT TO the existing output, never instead of it.

Reads (never writes): $CSS_BASE/review/ID_candidates.csv, ID_excluded.csv, ID_qc.json, ID_score.json; optional
$CSS_BASE/unified_engine/patient_keys.csv (exam -> patient). Writes ONLY $CSS_BASE/unified_engine/shadow/ID.json (atomic replace).
After the run it re-hashes every input file and records whether they are unchanged (they must be; the test suite asserts it).

Per candidate the result keeps three separate blocks plus the fusion:
  deterministic   the EXISTING output as recorded (score_v4, css / vein evidence, rule fate, review tiers) + its verbatim re-check
  characteristics measured inputs with status (ok / missing / corrupt / out of range / clipped) - label-free
  ml              learned increment and per-feature contributions, or 'withheld' with the reason
  unified         p, 5-95 % interval, category - or the DETERMINISTIC FALLBACK (source 'deterministic_fallback', no probability)
Fallback happens when: no healthy model, model incompatible / corrupt, model data_kind does not match the study (a synthetic model is
never applied to a real study), or any exception in the ML path. The deterministic block is computed first and is always present."""
import datetime, hashlib, json, os, traceback
import numpy as np
import pandas as pd
from . import ENGINE_VERSION, __version__, SYNTHETIC_STAMP, registry, math_component as mc, provenance as pv
from .prototype.inputs import sanitize
from .prototype.components import MathComponent, CharacteristicsComponent
from .prototype.fusion import UnifiedScorer

DISCLAIMER = ("SHADOW MODE - EXPERIMENTAL research output computed next to the existing result; it changes nothing in the existing "
              "scoring, lists, calls or exports. Not a diagnosis. Not clinically validated.")


def _sha(p):
    if not os.path.exists(p): return None
    with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()


def _json(p):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return None


def registration_state(qc):
    """same limits as the unified score (uscore.common.registration_state) - ok <= 0.5 mm, marginal <= 1.0, else unreliable"""
    if not qc: return "unverified"
    if str(qc.get("anatomy", "")).lower().startswith("swi"): return "swi_only"
    s = qc.get("label_shift_mm")
    if s is None: return "unverified"
    if qc.get("registration_ok") is False: return "unreliable"
    return "ok" if s <= 0.5 else ("marginal" if s <= 1.0 else "unreliable")


def _patient_key(base, sid):
    p = os.path.join(base, "unified_engine", "patient_keys.csv")
    if os.path.exists(p):
        try:
            m = pd.read_csv(p, dtype=str); r = m[m.exam_id == sid]
            if len(r): return str(r.patient_key.iloc[0]), True
        except Exception: pass
    return f"{sid}", False                                    # unverified: one study = one patient (recorded)


def _clean(v):
    if isinstance(v, (np.floating, float)): return None if not np.isfinite(v) else float(v)
    if isinstance(v, np.integer): return int(v)
    if isinstance(v, np.bool_): return bool(v)
    if isinstance(v, dict): return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [_clean(x) for x in v]
    return v


def load_study(base, sid):
    parts = []
    for lst, idc in (("candidates", "cand_id"), ("excluded", "excl_id")):
        p = os.path.join(base, "review", f"{sid}_{lst}.csv")
        if os.path.exists(p):
            d = pd.read_csv(p)
            if len(d): parts.append(d.assign(_list=lst, _ref=[f"{'c' if lst == 'candidates' else 'x'}{int(i)}" for i in d[idc]]))
    if not parts: raise FileNotFoundError(f"{sid}: no candidate list")
    return pd.concat(parts, ignore_index=True, sort=False)


def run_study(base, sid, synthetic=False, model_path=None, out_dir=None, write=True):
    base = os.path.abspath(base); out_dir = out_dir or os.path.join(base, "unified_engine", "shadow")
    inputs = {k: os.path.join(base, "review", f"{sid}_{k}") for k in ("candidates.csv", "excluded.csv", "qc.json", "score.json")}
    h0 = {k: _sha(p) for k, p in inputs.items()}
    qc = _json(inputs["qc.json"]) or {}; reg = registration_state(qc)
    pk, pk_verified = _patient_key(base, sid)
    res = dict(study=sid, engine=ENGINE_VERSION, engine_package=__version__, shadow_mode=True, experimental=True, synthetic=bool(synthetic),
               stamp=SYNTHETIC_STAMP if synthetic else "REAL STUDY - experimental shadow output only", disclaimer=DISCLAIMER,
               created=datetime.datetime.now().isoformat(timespec="seconds"), registration=reg, patient_key=pk, patient_key_verified=pk_verified,
               sources_verified=not pv.verify_sources(), detector_sha256=pv.DETECTOR_SHA256)
    D = load_study(base, sid)
    D = D.assign(patient_key=pk if synthetic else f"REAL:{pk}", exam_id=sid if synthetic else f"REAL:{sid}", cand_key=[f"{sid}#{r}" for r in D._ref],
                 registration=reg, measurement_complete=True, synthetic=bool(synthetic))
    if synthetic:                                              # synthetic identifiers satisfy the prototype guard
        D["patient_key"] = [p if str(p).startswith("SYN") else f"SYN-{p}" for p in D.patient_key]
        D["exam_id"] = [e if str(e).startswith("SYN") else f"SYN-{e}" for e in D.exam_id]
    Dc, rep = sanitize(D, require_synthetic=False)
    # ---- deterministic block (always; recorded values authoritative)
    M = MathComponent(); C = CharacteristicsComponent()
    det, chars = [], []
    for r in Dc.to_dict("records"):
        m = M.outputs(r); st = {c: s for (k, c), s in rep.status.items() if k == r["cand_key"]}; co, _ = C.outputs(r, st)
        det.append(dict(score_v4=m["score_v4"], score_v4_source=m["source"], score_v4_verbatim_check=m["status"], recomputed=m["recomputed"],
                        css_evidence=m["css_evidence"], vein_evidence=m["vein_evidence"], rule_fate=m["rule_fate"] or None,
                        review_tier=m["review_tier"], review_priority_rank=m["review_priority_rank"],
                        list="shown" if r["_list"] == "candidates" else "excluded", ref=r["_ref"]))
        chars.append(dict(values=co["values"], status=co["status"], n_missing_or_invalid=co["n_missing_or_invalid"]))
    # ---- ML + fusion (shadow; fallback on anything)
    mh = registry.health(model_path) if model_path else registry.active(base)
    apply, why = registry.apply_policy(mh, synthetic)
    ml_err = None; R = None
    if apply:
        try: R = UnifiedScorer.load(mh["path"]).predict(Dc)
        except Exception as e:
            ml_err = f"{type(e).__name__}: {e}"; apply = False; why = f"ML path failed - deterministic fallback ({ml_err})"
            res["ml_traceback"] = traceback.format_exc()[-1500:]
    cands = []
    for i, r in enumerate(Dc.to_dict("records")):
        c = dict(key=r["cand_key"], ref=r["_ref"], list=det[i]["list"], hemi=r.get("hemi"), region=r.get("region"),
                 deterministic=det[i], characteristics=chars[i])
        if R is not None:
            x = R[i]; c["ml"] = dict(status="applied", **x.learned); c["unified"] = dict(source="fusion", **x.unified)
            c["quality_flags"] = x.quality_flags; c["trace"] = x.trace
        else:
            c["ml"] = dict(status="withheld", reason=why)
            c["unified"] = dict(source="deterministic_fallback", p=None, p_lo=None, p_hi=None, category=None,
                                reasons=["ML not applied - the existing deterministic output stands"], score_v4=det[i]["score_v4"])
            c["quality_flags"] = [f"registration {reg}"] if reg not in ("ok",) else []
        cands.append(_clean(c))
    cats = {k: sum((c["unified"].get("category") == k) for c in cands) for k in ("likely_cSS", "uncertain", "unlikely_cSS", "not_scorable")}
    res.update(model=_clean({k: v for k, v in mh.items() if k != "card"}), model_card=_clean(mh.get("card") or {}), ml_applied=R is not None,
               ml_status=why, ml_error=ml_err, n_candidates=len(cands), n_shown=sum(c["list"] == "shown" for c in cands),
               category_counts=cats if R is not None else None,
               deterministic_patient_score=_clean(mc.patient_score(_json(inputs["score.json"]))),
               input_validation=dict(corrupt=rep.corrupt, out_of_range=rep.out_of_range), candidates=cands)
    h1 = {k: _sha(p) for k, p in inputs.items()}
    res["inputs_sha256"] = h0; res["original_outputs_unchanged"] = h0 == h1
    if write:
        os.makedirs(out_dir, exist_ok=True); tmp = os.path.join(out_dir, f".{sid}.json.tmp")
        with open(tmp, "w") as f: json.dump(res, f, indent=1, default=str)
        os.replace(tmp, os.path.join(out_dir, f"{sid}.json"))
    return res


def deterministic_only(base, sid):
    """in-process fallback used by the GUI when the engine subprocess cannot run at all: recorded deterministic columns only
    (no engine logic, no model) - the existing output exactly as the detector wrote it"""
    D = load_study(base, sid); keep = ["_ref", "_list", "hemi", "region", "score_v4", "css_evidence", "vein_evidence", "rule_version",
                                       "review_tier", "review_priority_rank"]
    D = D[[c for c in keep if c in D.columns]]
    return [_clean(dict(ref=r["_ref"], list="shown" if r["_list"] == "candidates" else "excluded", **{k: r.get(k) for k in keep[2:]}))
            for r in D.to_dict("records")]
