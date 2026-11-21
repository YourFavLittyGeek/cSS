"""training_gui.py - back end of the Training screen (v5.17): four separate sections, every number labelled by its data kind
(SYNTHETIC or CLINICAL) and its source; synthetic and clinical performance are never combined. Research software.
  A Image ML           image models (architecture, version, training data, local weights + hash, synthetic evaluation), inference status
  B Characteristic ML  deterministic MATH (detector), the Stage 1 Unified Score engine models (shadow), the project's Unified Score (uscore)
    / Unified Score
  C Expert labels      css-labels/2.0 counts (class, subtype, confidence), reviewers, adjudication (consensus), label provenance, call rule
  D Model evaluation   sensitivity / specificity, ROC-AUC, precision-recall, calibration, confusion matrix, false positives / negatives,
                       patient-level split; separate panels per data kind
The image engine is used through its command line (subprocess), as on the Image ML screen."""
import glob, json, os, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "unified_engine", "run_imaging.py")
JOB = dict(status="idle"); LOCK = threading.Lock()


def _jl(p):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return None


def image_models(B):
    try:
        r = subprocess.run([sys.executable, CLI, "models", "--base", B, "--cards"], capture_output=True, text=True, timeout=60, env=dict(os.environ, CSS_BASE=B))
        return json.loads(r.stdout) if r.returncode == 0 else []
    except Exception: return []


def evals(AD):
    out = []
    for p in sorted(glob.glob(os.path.join(AD, "eval", "image_eval_*.json")), reverse=True)[:5]:
        d = _jl(p)
        if d: d["file"] = os.path.basename(p); out.append(d)
    return out


def run_evaluation(AD, n=12, seed=None):
    """background: score the active image model on a fresh SYNTHETIC cohort (the model is only read)"""
    with LOCK:
        if JOB.get("status") == "running": return dict(ok=False, error="an evaluation is already running")
        JOB.update(status="running", started=time.time(), error="")
    out = os.path.join(AD, "eval", f"image_eval_{time.strftime('%Y%m%d_%H%M%S')}.json"); os.makedirs(os.path.dirname(out), exist_ok=True)
    def go():
        try:
            r = subprocess.run([sys.executable, CLI, "evaluate-synthetic", out, "--n", str(n), "--seed", str(seed or int(time.time()) % 100000)],
                               capture_output=True, text=True, timeout=1800)
            ok = r.returncode == 0; err = "" if ok else (r.stderr or r.stdout)[-400:]
        except Exception as e: ok, err = False, f"{type(e).__name__}: {e}"
        with LOCK: JOB.update(status="completed" if ok else "failed", finished=time.time(), error=err)
    threading.Thread(target=go, daemon=True).start()
    return dict(ok=True, started=True)


def labels(B):
    try:
        sys.path.insert(0, os.path.join(B, "scripts")) if os.path.exists(os.path.join(B, "scripts", "label_schema.py")) else sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import label_schema as LS
        df = LS.build(B); s = LS.summary(df)
        s["by_source"] = df.source_schema.value_counts().to_dict() if len(df) else {}
        s["confidence"] = df.confidence.value_counts().to_dict() if len(df) else {}
        s["by_reviewer"] = df.reviewer_id.value_counts().to_dict() if len(df) else {}
        cons = os.path.join(B, "labels", "consensus.csv")
        if os.path.exists(cons):
            import pandas as pd
            c = pd.read_csv(cons, dtype=str); s["adjudication"] = c["method"].value_counts().to_dict() if "method" in c.columns else {}
        else: s["adjudication"] = {}
        return s
    except Exception as e: return dict(error=f"{type(e).__name__}: {e}"[-300:])


def overview(B, AD, PAT, SET, version, shadow_models, uscore_state, uscore_validation, calls_policy):
    synthetic_base = os.path.exists(os.path.join(B, "unified_engine", "SYNTHETIC_BASE"))
    im = image_models(B)
    n_res = len(glob.glob(os.path.join(B, "unified_engine", "image_ml", "*.json")))
    A = dict(models=im, inference=dict(results=n_res, applies_to="synthetic studies only (no clinical image model exists)", synthetic_base=synthetic_base),
             evaluations=evals(AD), job=dict(JOB))
    try: sm = shadow_models()
    except Exception as e: sm = dict(error=str(e))
    try: us = uscore_state()
    except Exception as e: us = dict(error=str(e))
    try: uv = uscore_validation()
    except Exception as e: uv = dict(available=False, error=str(e))
    mi = (uv or {}).get("model") or {}
    uv_kind = "synthetic" if mi.get("synthetic_test") else ("clinical" if (uv or {}).get("available") else "")
    Bsec = dict(math=dict(detector=version(), description="deterministic rules (score_v4, exclusions, tiers) executed as recorded; never retrained"),
                shadow=dict(models=(sm or {}).get("models", []), error=(sm or {}).get("error", "")),
                uscore=dict(enabled=bool((SET.get("features") or {}).get("unified_score")), model=mi, heldout=(us or {}).get("heldout"), split=(us or {}).get("split")))
    try: pol = calls_policy()
    except Exception as e: pol = dict(error=str(e))
    C = dict(labels=labels(B), calls_rule=((pol or {}).get("policy") or {}).get("default"), reviewers=(pol or {}).get("reviewers", []))
    D = dict(synthetic=dict(image_ml=A["evaluations"][:1], note="synthetic generator only - not an estimate of clinical performance"),
             clinical=dict(uscore=uv if uv_kind == "clinical" else None, image_ml=None,
                           note="no clinical evaluation of any image model exists" + ("" if uv_kind == "clinical" else "; no clinical Unified Score validation report yet")),
             uscore_kind=uv_kind, uscore_synthetic=uv if uv_kind == "synthetic" else None,
             split=dict(rule="patient-level: every split, fold, calibration and bootstrap is grouped by patient (and repeat examinations)",
                        heldout=(us or {}).get("heldout")))
    return dict(synthetic_base=synthetic_base, A=A, B=Bsec, C=C, D=D)
