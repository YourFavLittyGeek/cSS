"""component_registry.py - versioned, reversible configurations of the PERCIVAL specialist components (ALBUS, NOX, LUMOS).

<store>/components/<COMPONENT>/vNNN.json   one immutable version: configuration, parent version, who approved it and why, the evidence
                                           (SHADOW proposal + PERCIVAL confirmation, or ALBUS detector evaluation), synthetic flag
<store>/components/<COMPONENT>/active.json pointer to the active version (absent = the built-in baseline v000)
<store>/components/<COMPONENT>/history.jsonl  append-only: created / activated / rolled back, with person and reason
A new version is created ONLY by approve() - which needs a named person who is not an automated actor, the typed phrase, and a reason.
Nothing here changes the detector, a model or a label: the registry records what was approved; the components read it explicitly."""
import json
import os
import time

COMPONENTS = ("ALBUS", "NOX", "LUMOS")
CONFIRM = "APPROVE COMPONENT CHANGE"
AUTOMATED = {"", "shadow", "percival", "system", "auto", "automatic", "albus", "nox", "lumos", "core", "pensieve"}
BASELINES = dict(
    NOX=dict(feature_set=["darkness_z", "edge_contrast", "pial_dist_mm", "cortex_frac", "tram_frac", "tube_ratio", "elongation_3d",
                          "log_volume_mm3", "local_cont_max_mm"], predictors="uScore x1-x5 (reliable values)",
             note="built-in: the 9 detector measurements of the PERCIVAL Decision Engine + uScore x1-x5"),
    ALBUS=dict(detector="scripts/detect_css.py", note="built-in: the installed detector and its rule set (review/ID_manifest.json per study)"),
    LUMOS=dict(network="percival SmallCNN (registry image component)", note="built-in: the image network of the active PERCIVAL model"))


class RegistryError(PermissionError):
    pass


def _d(store, comp):
    if comp not in COMPONENTS: raise RegistryError(f"unknown component {comp}")
    return os.path.join(store, "components", comp)


def _js(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as f: json.dump(obj, f, indent=1, sort_keys=True, default=str); f.flush(); os.fsync(f.fileno())
    os.replace(p + ".tmp", p)


def _jl(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d


def _log(store, comp, **ev):
    p = os.path.join(_d(store, comp), "history.jsonl"); os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a") as f: f.write(json.dumps(dict(ev, at=time.strftime("%Y-%m-%d %H:%M:%S")), sort_keys=True, default=str) + "\n"); f.flush(); os.fsync(f.fileno())


def versions(store, comp):
    d = _d(store, comp)
    return sorted(f[:-5] for f in os.listdir(d) if f.startswith("v") and f.endswith(".json")) if os.path.isdir(d) else []


def load(store, comp, v):
    if v == "v000": return dict(version="v000", component=comp, config=BASELINES[comp], parent=None, by="built-in", baseline=True, signature_ok=True)
    V = _jl(os.path.join(_d(store, comp), f"{v}.json"))
    if V is not None:                                                     # Stage 7: local integrity signature (approval_signing.py)
        from uengine import approval_signing as AS
        V["signature_ok"] = AS.verify(V)
    return V


def active(store, comp):
    a = _jl(os.path.join(_d(store, comp), "active.json")) or {}
    return load(store, comp, a.get("version", "v000"))


def history(store, comp):
    p = os.path.join(_d(store, comp), "history.jsonl")
    if not os.path.exists(p): return []
    with open(p) as f: return [json.loads(x) for x in f if x.strip()]


def _check_person(by, reason, confirm):
    if confirm != CONFIRM: raise RegistryError(f"refused: type exactly '{CONFIRM}' to confirm")
    if str(by or "").strip().lower() in AUTOMATED: raise RegistryError("refused: approval needs a named person (automated actors cannot approve)")
    if not str(reason or "").strip(): raise RegistryError("refused: a reason is required")


def approve(store, comp, config, by, reason, confirm, evidence, synthetic=False):
    """create AND activate a new version (the previous one stays available for rollback). evidence: the proposal / evaluation record."""
    _check_person(by, reason, confirm)
    cur = active(store, comp); v = f"v{len(versions(store, comp)) + 1:03d}"
    V = dict(version=v, component=comp, config=config, parent=cur["version"], by=str(by).strip(), reason=str(reason).strip(),
             created=time.strftime("%Y-%m-%d %H:%M:%S"), evidence=evidence, synthetic=bool(synthetic),
             note="SYNTHETIC evidence - infrastructure test only, not a validated improvement" if synthetic else "")
    from uengine import approval_signing as AS
    V["signature"] = AS.sign(V)
    _js(os.path.join(_d(store, comp), f"{v}.json"), V)
    _js(os.path.join(_d(store, comp), "active.json"), dict(version=v, previous=cur["version"], by=V["by"], at=V["created"]))
    _log(store, comp, event="approved_and_activated", version=v, parent=cur["version"], by=V["by"], reason=V["reason"], synthetic=bool(synthetic))
    from uengine import event_log as EV                                     # Stage 5: the event log is authoritative for active versions
    EV.append(store, "component_change", V["by"], component=comp, version=v, parent=cur["version"], reason=V["reason"], synthetic=bool(synthetic),
              signature=V.get("signature"))
    return V


def rollback(store, comp, by, reason, confirm):
    """re-activate the parent of the active version (the newer version is kept, marked rolled back)"""
    _check_person(by, reason, confirm)
    cur = active(store, comp)
    if cur["version"] == "v000": raise RegistryError("nothing to roll back: the built-in baseline is active")
    prev = cur.get("parent") or "v000"
    _js(os.path.join(_d(store, comp), "active.json"), dict(version=prev, previous=cur["version"], by=str(by).strip(), at=time.strftime("%Y-%m-%d %H:%M:%S"),
                                                         rolled_back=cur["version"]))
    _log(store, comp, event="rolled_back", version=cur["version"], now_active=prev, by=str(by).strip(), reason=str(reason).strip())
    from uengine import event_log as EV
    EV.append(store, "rollback", str(by).strip(), component=comp, rolled_back=cur["version"], now_active=prev, reason=str(reason).strip())
    return load(store, comp, prev)


def overview(store):
    return {c: dict(active=active(store, c), versions=["v000"] + versions(store, c), history=history(store, c)[-20:]) for c in COMPONENTS}
