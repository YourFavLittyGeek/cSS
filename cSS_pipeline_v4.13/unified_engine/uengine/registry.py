"""registry.py - PAST EXPERIENCE model loading, versioning, metadata and health / compatibility checks.

A model is one JSON file written by UnifiedScorer.save() plus a 'card' block (name, version, created, data_kind, training data,
intended use, synthetic evaluation). Search order: $CSS_BASE/unified_engine/models/*.json (user-provided, read-only here), then the
bundled unified_engine/models/*.json. The active model is the newest healthy model unless $CSS_BASE/unified_engine/config.json names one.

health(path) -> dict(status, reasons, ...). status:
  ok            hash, schema, detector and engine version verified; may be applied to studies of its data_kind
  incompatible  schema / detector / engine-major version / mode differs from this engine (never applied)
  corrupt       unreadable or content does not match its hash (never applied)
  missing       no file
Applicability (apply_policy): a model whose data_kind is 'synthetic' is applied ONLY to synthetic studies. There is no clinical model;
for real studies the engine reports 'withheld' and falls back to the deterministic MATH output."""
import glob, json, os
from . import ENGINE_VERSION, provenance as pv
from .prototype.fusion import UnifiedScorer, schema_hash, MODES

BUNDLED = os.path.join(pv.ENGINE, "models")


def model_dirs(base=None):
    d = [os.path.join(base, "unified_engine", "models")] if base else []
    return d + [BUNDLED]


def _read(path):
    with open(path) as f: return json.load(f)


def health(path):
    if not path or not os.path.exists(path): return dict(status="missing", reasons=["no model file"], path=path)
    try: d = _read(path)
    except Exception as e: return dict(status="corrupt", reasons=[f"unreadable: {type(e).__name__}"], path=path)
    card = d.get("card") or {}; P = d.get("params") or {}; r = []
    out = dict(path=path, name=card.get("name"), version=card.get("version"), data_kind=card.get("data_kind"), created=card.get("created"),
               model_hash=d.get("model_hash"), mode=P.get("mode"), engine=P.get("prototype"), card=card)
    try: UnifiedScorer.load(path)
    except ValueError as e:
        msg = str(e); out.update(status="corrupt" if "hash" in msg else "incompatible", reasons=[msg]); return out
    except Exception as e:
        out.update(status="corrupt", reasons=[f"cannot be loaded: {type(e).__name__}: {e}"]); return out
    if str(P.get("prototype", "")).split("/")[0] != "uengine-fusion" or str(P.get("prototype", "")).split("/")[-1].split(".")[0] != "1":
        r.append(f"engine version {P.get('prototype')} is not compatible with {ENGINE_VERSION}")
    if P.get("mode") not in MODES: r.append(f"unknown fusion mode {P.get('mode')}")
    if card.get("data_kind") not in ("synthetic",): r.append(f"data_kind {card.get('data_kind')!r} not supported by this engine")
    if P.get("schema_sha256") != schema_hash(P.get("columns", [])): r.append("feature schema differs")
    if (P.get("training") or {}).get("data_kind") != card.get("data_kind"):
        r.append("card data_kind disagrees with the hash-protected training record (card edited?)")
    out.update(status="incompatible" if r else "ok", reasons=r)
    return out


def list_models(base=None):
    out = []
    for d in model_dirs(base):
        for f in sorted(glob.glob(os.path.join(d, "*.json"))): out.append(health(f))
    return out


def active(base=None):
    """-> health dict of the model to use (or a 'missing' record). Never raises."""
    try:
        cfg = os.path.join(base, "unified_engine", "config.json") if base else None
        want = _read(cfg).get("active_model") if cfg and os.path.exists(cfg) else None
        ms = list_models(base)
        if want:
            m = next((x for x in ms if x.get("name") == want or os.path.basename(x["path"]) == want), None)
            return m or dict(status="missing", reasons=[f"configured model {want!r} not found"], path=None)
        ok = [m for m in ms if m["status"] == "ok"]
        return sorted(ok, key=lambda m: str(m.get("created")))[-1] if ok else (ms[0] if ms else dict(status="missing", reasons=["no model installed"], path=None))
    except Exception as e:
        return dict(status="corrupt", reasons=[f"registry error: {type(e).__name__}: {e}"], path=None)


def apply_policy(model_health, study_is_synthetic):
    """-> (apply: bool, reason)"""
    if model_health.get("status") != "ok": return False, f"model {model_health.get('status')}: {'; '.join(model_health.get('reasons', []))}"
    if model_health.get("data_kind") == "synthetic" and not study_is_synthetic:
        return False, "only a SYNTHETIC-trained model is installed; it is never applied to a real study (no clinically trained model exists)"
    return True, "applied (synthetic model on a synthetic study)"


def save_with_card(scorer, path, card):
    """writes the model file + card; refuses to overwrite an existing file (models are never replaced in place)"""
    if os.path.exists(path): raise FileExistsError(f"{path} exists - models are never overwritten; choose a new version name")
    scorer.save(path); d = _read(path); d["card"] = dict(card)
    with open(path, "w") as f: json.dump(d, f, indent=1, default=str)
    return health(path)
