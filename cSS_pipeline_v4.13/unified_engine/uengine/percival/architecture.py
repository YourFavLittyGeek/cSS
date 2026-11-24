"""architecture.py - the PERCIVAL architecture over the WORKING implementation (no second detector, CNN or scoring engine).

Mapping (docs/engineering/ARCHITECTURE_RECONCILIATION.md; user-facing names in NAMES):
  ALBUS   Mathematical Detection        scripts/detect_css.py: candidate generation, rules E1-E30, score_v4 (Percival component 'math')
  NOX     Quantitative MRI Analysis     detector measurements CHAR (component 'char') + uScore x1-x5 predictors (component 'unified')
  LUMOS   Visual Intelligence           the Percival SmallCNN on MRI patches (component 'image'); the SAME trained weights
  PERCIVAL Decision Engine              the trainable meta-model + calibration + OOD + thresholds (uengine/percival/meta.py)
  CORE    Fixed-Weight Baseline         uengine/percival_core.py - comparison only, never a PERCIVAL prediction
  fusion  NOX x LUMOS fusion            an internal PERCIVAL input (characteristics + image logit)

candidate_contract()  one record per candidate: identity, ALBUS / NOX / LUMOS evidence with an explicit state, the PERCIVAL decision,
                      pairwise disagreement of every available specialist pair, component versions, provenance. No patient identifier
                      unless include_patient=True (never in reviewer-facing output).
Every evidence block has a state: valid | missing | untrained | uncalibrated | failed | not_applicable. Missing evidence is NEVER a
negative prediction: its value is None."""
import hashlib
import json
import os

SCHEMA = "percival-candidate-contract/1.0"
NAMES = dict(PERCIVAL="PERCIVAL · Integrated cSS AI system", ALBUS="ALBUS · Mathematical Detection", NOX="NOX · Quantitative MRI Analysis",
             LUMOS="LUMOS · Visual Intelligence", PENSIEVE="PENSIEVE · AI Memory and History", SHADOW="SHADOW · Experimental Discovery Lab",
             CORE="CORE · Fixed-Weight Baseline", ENGINE="PERCIVAL Decision Engine")
# Percival engine component -> architecture component (the engine's internal names are kept: data contracts of saved models)
OWNER = dict(math="ALBUS", char="NOX", unified="NOX", image="LUMOS", fusion="PERCIVAL")
LABEL = dict(math="ALBUS · detector score (score_v4, recalibrated)", char="NOX · detector measurements", unified="NOX · uScore x1–x5 predictors",
             image="LUMOS · MRI patch CNN", fusion="PERCIVAL · NOX × LUMOS fusion")
SPECIALISTS = ("math", "char", "unified", "image")
STATES = ("valid", "missing", "untrained", "uncalibrated", "failed", "not_applicable")


def _h(obj): return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def detector_version(base, sid):
    """ALBUS version of one study's candidate list: detector build + rule set + hash of the parameters (review/ID_manifest.json)"""
    try:
        with open(os.path.join(base, "review", f"{sid}_manifest.json")) as f: m = json.load(f)
    except Exception: return dict(state="missing", version=None, reason="no detector manifest (review/ID_manifest.json)")
    d = m.get("detect") or {}
    ver = dict(build=m.get("build") or d.get("build"), ruleset=d.get("pipeline_version"), parameters_sha=_h(d.get("parameters") or {}),
               anatomy=d.get("anatomy"), run_at=d.get("run_at"))
    ver["version"] = f"albus:{ver['ruleset'] or '?'}:{(ver['build'] or 'nobuild')[:12]}:{ver['parameters_sha']}"
    ver["state"] = "valid"; return ver


def component_versions(model):
    """content hashes of each trained engine component of a registry model (component-level version records)"""
    C = (model or {}).get("components") or {}; out = {}
    for k in ("math", "unified", "char", "image", "fusion"):
        if C.get(k) is not None: out[k] = dict(owner=OWNER[k], sha256=_h(C[k]), kind=((C.get("kinds") or {}).get(k) if k in ("char", "image", "fusion") else
                                                                                     "platt" if k == "math" else "logistic"))
    if (model or {}).get("meta"): out["meta"] = dict(owner="PERCIVAL", sha256=_h(model["meta"]), kind=model["meta"].get("kind"))
    if (model or {}).get("calibration"): out["calibration"] = dict(owner="PERCIVAL", sha256=_h(model["calibration"]), kind="platt")
    return out


def lumos_state(model):
    """is a TRAINED LUMOS network available? (the Percival image component of the active model - never a random initialisation)"""
    if not model: return dict(state="untrained", reason="no PERCIVAL model is active - LUMOS has no trained weights yet")
    im = (model.get("components") or {}).get("image")
    if im is None: return dict(state="untrained", reason=f"model {model.get('version')} was trained without an image network (too few patches)")
    return dict(state="valid", source=f"registry {model.get('version')} (Percival image component)", kind=im.get("type"), sha256=_h(im),
                calibrated=False, calibration_note="component logit; calibrated only inside the PERCIVAL decision (meta-model + Platt)")


def pairwise(model, comps_pct):
    """agreement pattern of every available specialist pair at scoring, with the cSS rate seen in expert-reviewed development cases with
    that pattern (model.intelligence.disagreement; patient-grouped out-of-fold predictions). comps_pct: {component: 0-100 or None}"""
    from . import intelligence as IN
    import math
    table = ((model or {}).get("intelligence") or {}).get("disagreement") or []
    lg = {k: (None if v is None else math.log(max(1e-6, v / 100) / max(1e-6, 1 - v / 100))) for k, v in (comps_pct or {}).items()}
    out = []
    keys = [k for k in ("math", "unified", "char", "image", "fusion") if k in lg]
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if lg[a] is None or lg[b] is None: continue
            p = IN.pattern_of(table, a, b, lg[a], lg[b])
            agree = (lg[a] >= 0) == (lg[b] >= 0)
            out.append(dict(pair=f"{OWNER[a]}:{a} vs {OWNER[b]}:{b}", a=a, b=b, agree=agree,
                            pattern=(p or {}).get("pattern") or ("both_high" if lg[a] >= 0 and lg[b] >= 0 else "both_low" if agree else f"{a if lg[a] >= 0 else b}_only"),
                            css_rate=(p or {}).get("css_rate"), n=(p or {}).get("n"), ci=(p or {}).get("ci"),
                            basis="expert-reviewed development cases with this pattern" if p else "no development history for this pair"))
    return out


def candidate_contract(sid, scored, row=None, model=None, albus=None, include_patient=False, review=None):
    """scored: one candidate of score_study (meta.score_rows output); row: its gathered row (char, pred, maps, math); albus: detector_version()"""
    row = row or {}; comps = scored.get("components") or {}
    char = row.get("char") or {}; pred = row.get("pred") or {}
    nchar = sum(v is not None for v in char.values()); npred = sum(v is not None for v in pred.values())
    lst = lumos_state(model)

    def ev(k, state_if_present="valid"):
        v = comps.get(k)
        return v, (state_if_present if v is not None else "missing")
    a_v, a_s = ev("math"); c_v, c_s = ev("char"); u_v, u_s = ev("unified"); i_v, i_s = ev("image")
    if lst["state"] != "valid": i_s, i_v = lst["state"], None
    rec = dict(schema=SCHEMA, identity=dict(study=sid, cand_id=scored.get("cand_id"), hemi=scored.get("hemi"),
                                            fingerprint=None if not row else {k: row.get(k) for k in ("vox_i", "vox_j", "vox_k", "volume_mm3") if k in row} or None),
               albus=dict(name=NAMES["ALBUS"], state=a_s if albus is None or albus.get("state") == "valid" else "failed",
                          score_v4=row.get("math"), recalibrated_pct=a_v, version=(albus or {}).get("version")),
               nox=dict(name=NAMES["NOX"], measurements=dict(state="valid" if nchar else "missing", n_available=nchar, n_total=len(char), values=char,
                                                             component_pct=c_v),
                        predictors_x1_x5=dict(state="valid" if npred else "missing", n_reliable=npred, values=pred, component_pct=u_v,
                                              note="uScore x1–x5 feature values (reliable only); the separate uScore scorer is not used")),
               lumos=dict(name=NAMES["LUMOS"], state=i_s, component_pct=i_v, patch=("available" if row.get("maps") is not None else "missing") if row else None,
                          tta_spread=scored.get("image_tta_spread"), image_ood_distance=scored.get("image_ood_distance"), weights=lst),
               percival=dict(name=NAMES["ENGINE"], score=scored.get("percival_score"), band=scored.get("band"), status=scored.get("status"),
                             reasons=scored.get("reasons"), uncertainty_sd=scored.get("uncertainty_sd"), spread=scored.get("disagreement"),
                             ood_distance=scored.get("ood_distance"), missing_inputs=scored.get("missing"), fusion_pct=comps.get("fusion"),
                             model=(model or {}).get("version"), pairwise=pairwise(model, comps)),
               provenance=dict(model=(model or {}).get("version"), dataset=((model or {}).get("data") or {}).get("dataset"),
                               component_versions=component_versions(model) if model else {}),
               kind="AI prediction - not an expert label")
    if scored.get("experimental_core") is not None:
        rec["core"] = dict(name=NAMES["CORE"], role="comparison only - never the PERCIVAL prediction", **scored["experimental_core"])
    if review is not None: rec["expert_review"] = review                      # reference only (ledger status), never merged into the prediction
    if include_patient: rec["identity"]["patient"] = row.get("patient")
    return rec


def component_report(model):
    """per-architecture-component evaluation of one trained model (everything was computed by train_cycle on the development cohort's
    patient-grouped OUT-OF-FOLD predictions; the locked test numbers are kept separate). Nothing is recomputed or invented here."""
    if not model: return dict(available=False, reason="no trained PERCIVAL model yet")
    cm = model.get("component_metrics") or {}; intel = model.get("intelligence") or {}; te = model.get("test") or {}
    abl = intel.get("ablation") or {}
    comp = {}
    for k in ("math", "char", "unified", "image", "fusion"):
        comp[k] = dict(owner=OWNER[k], label=LABEL[k], development_oof=cm.get(k), available=cm.get(k) is not None)
    owners = {}
    for k, v in comp.items(): owners.setdefault(v["owner"], []).append(k)
    return dict(available=True, model=model.get("version"), basis="development cohort, patient-grouped out-of-fold (single level; optimistic for selection)",
                components=comp, by_owner=owners,
                percival=dict(chosen_meta_model=(model.get("discovery") or {}).get("chosen"), nested_development=(model.get("nested") or {}).get("percival"),
                              locked_test=te.get("percival"), detector_alone_locked_test=te.get("math"), calibration=model.get("calibration"),
                              thresholds=model.get("thresholds"), acceptance=model.get("acceptance")),
                ablation=abl, pairwise_disagreement=intel.get("disagreement"), reliability=intel.get("reliability"),
                ood=dict(measurements=((model.get("components") or {}).get("ood") or {}).get("limit"),
                         image=((model.get("components") or {}).get("image_ood") or {}).get("limit")),
                split=(model.get("data") or {}).get("split"), dataset=(model.get("data") or {}).get("dataset"),
                component_versions=model.get("component_versions") or component_versions(model),
                separation=dict(training="development partition (components + meta-model)", validation="nested cross-fitting on development",
                                confirmation="SHADOW proposals: confirmation patients of the development partition (shadow_governed)",
                                independent_test="locked test patients - evaluated once per model, never used to fit or select inside a cycle",
                                discovery="SHADOW discovery patients only"))
