"""percival_gui.py - the app side of PERCIVAL SCORE (v5.22). Everything runs on this computer (numpy); nothing is uploaded; no external
model or AI service is used (see docs/percival_app/LOCAL_AI_ARCHITECTURE.md).

  authorize()        the user's one-time switch for LOCAL learning on this project's MRI (app_data/ml_authorization.json, audited);
                     synthetic SYN studies of a synthetic project never need it
  gather(sid)        candidate rows of one study: MATH (score_v4), the 5 Unified-Score predictors (uscore/features, extracted when
                     missing), the 9 detector characteristics, the image maps of the candidate's MRI patch, the expert label (effective
                     reviewer call: definite cSS = 1, definite mimic = 0; indeterminate / out of scope are not used), the locked-test flag
  integrity()        data checks before a cycle: uncertain labels excluded, reviewer conflicts flagged, duplicate studies (same images)
                     counted once, per-patient weighting inside the models
  train_async()      ONE controlled training cycle (meta.train_cycle): components, meta-model discovery, calibration, thresholds, locked-test
                     evaluation, acceptance; promoted only when it passes; every version kept in the registry (registry/vNNN/)
  maybe_cycle()      the watcher starts a cycle when N newly finished studies have accumulated (setting percival_cycle_n, default 5) -
                     the active model is never changed after a single review
  score_study()      Percival Score 0-100 + band + status per candidate with the active model; written to the PREDICTION LEDGER
                     ledger/ID/<model>__<run>.json (immutable - a new model never rewrites an old assessment) and scores/ID.json (current)
  promote / rollback any registry version can be made active; the previous one is kept.
  snapshot_reviews() v5.23: one immutable record per final expert review (reviews/ID/<reviewer>__<saved>.json): the labels, whether the
                     Percival Score was visible to the reviewer, the prediction that existed when the review was saved, coordinates,
                     measurements, patch hashes, processing / model versions - the provenance of the local learning dataset.
Files name studies by their internal key; no identifier is written here."""
import glob, hashlib, json, os, subprocess, sys, threading, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "unified_engine"), os.path.join(ROOT, "unified_score")):
    if p not in sys.path: sys.path.insert(0, p)
CTX = {}; LOCK = threading.Lock(); GLOCK = threading.RLock(); JOB = dict(state="idle", log=[], progress=0.0, error="")


def init(**ctx):
    CTX.update(ctx)
    if ctx.get("SC") and ctx["SC"] not in sys.path: sys.path.insert(0, ctx["SC"])
def B(): return CTX["B"]
def P(*a): return os.path.join(B(), "unified_engine", "percival", *a)
def _jl(p, d):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d
def _js(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as f: json.dump(o, f, default=float)
    os.replace(p + ".tmp", p)
def log(msg, prog=None):
    with LOCK:
        JOB["log"] = (JOB["log"] + [f"{time.strftime('%H:%M:%S')} {msg}"])[-300:]
        if prog is not None: JOB["progress"] = prog


# ------------------------------------------------------------------ authorisation
def auth_path(): return os.path.join(B(), "app_data", "ml_authorization.json")
def authorized(): return bool(_jl(auth_path(), {}).get("local_learning"))
def authorize(on, by="app user"):
    d = _jl(auth_path(), {"history": []}); d["local_learning"] = bool(on)
    d.setdefault("history", []).append(dict(at=time.strftime("%Y-%m-%d %H:%M:%S"), by=by, on=bool(on)))
    d["scope"] = "local learning on this project's MRI and expert reviews, on this computer only; no upload; no external AI service"
    _js(auth_path(), d); return dict(ok=True, authorized=bool(on))
def synthetic(sid):
    from uengine.imaging.index import is_synthetic_study
    return is_synthetic_study(B(), sid)
def may_read(sid): return authorized() or synthetic(sid)


# ------------------------------------------------------------------ one study's candidates
def _labels(sid):
    import label_schema as LS, pandas as pd
    p = os.path.join(B(), "review", f"{sid}_calls.csv")
    if not os.path.exists(p): return {}, 0
    d = pd.read_csv(p, dtype=str).fillna(""); out, unused = {}, 0
    for _, r in d.iterrows():
        try: cls, _, _ = LS.from_call(r.get("call", ""), r.get("fine_code", ""))
        except Exception: unused += 1; continue
        cid = int(float(r["cand_id"]))
        if cls == "definite_css": out[cid] = 1
        elif cls == "definite_mimic": out[cid] = 0
        else: unused += 1
    return out, unused


def _conflicts(sid):
    """candidates on which reviewers disagree (any two reviewer files with different calls) - reported; the effective call is used"""
    import pandas as pd
    calls = {}
    for f in glob.glob(os.path.join(B(), "review", f"{sid}_calls_*.csv")):
        try:
            d = pd.read_csv(f, dtype=str).fillna("")
            for _, r in d.iterrows(): calls.setdefault(str(r["cand_id"]), set()).add(r.get("call", ""))
        except Exception: pass
    return sorted(c for c, v in calls.items() if len(v - {""}) > 1)


def _predictors(sid):
    p = os.path.join(B(), "uscore", "features", f"{sid}.json")
    if not os.path.exists(p):
        try:
            from uscore import pipeline as PL, common as CM
            class _AppCohort:
                synthetic = False
                def role(self, s): raise CM.CohortError("application")
            PL.extract_study(B(), sid, _AppCohort(), os.path.join(B(), "uscore"), application=True)
        except Exception as e: log(f"{CTX['label'](sid)}: predictors not extracted ({type(e).__name__})")
    d = _jl(p, None) or {}; from uengine.percival.meta import PREDICTORS; out = {}
    for r in d.get("records", []):
        F = r.get("F", {}); out[int(r["cand_id"])] = {k: (float(F[k]["value"]) if F.get(k, {}).get("status") == "reliable" and F[k].get("value") is not None else None) for k in PREDICTORS}
    return out


def _maps(sid):
    from uengine.imaging import patches as PT
    from uengine.percival.cnn import patch_maps
    try: E = PT.extract_study(B(), sid)
    except Exception as e: log(f"{CTX['label'](sid)}: image patches not made ({type(e).__name__}: {str(e)[:80]})"); return {}
    if E.get("blocked"): log(f"{CTX['label'](sid)}: image patches not made ({E['blocked'][:80]})"); return {}
    out = {}
    for k, a in E["patches"].items():
        if k[0] == "candidates":
            m = patch_maps(a)
            if m is not None: out[int(k[1])] = m
    return out


def gather(sid, labelled=True):
    """thread-safe (v5.23): the watcher's review snapshots and a training cycle may gather the same study at the same time"""
    with GLOCK: return _gather(sid, labelled)


def _gather(sid, labelled=True):
    import pandas as pd
    from uengine.percival.meta import CHAR, test_assignment
    cp = os.path.join(B(), "review", f"{sid}_candidates.csv")
    if not os.path.exists(cp): return []
    deps = [cp, os.path.join(B(), "uscore", "features", f"{sid}.json")]
    key = [round(os.path.getmtime(p), 3) if os.path.exists(p) else 0 for p in deps] + [int(may_read(sid))]
    cj, cz = P("cache", f"{sid}.json"), P("cache", f"{sid}.npz"); C = _jl(cj, {})
    if C.get("key") != key or C.get("v") != 3 or not os.path.exists(cz):
        cand = pd.read_csv(cp); pred = _predictors(sid); maps = _maps(sid) if may_read(sid) else {}
        rows = []
        for _, r in cand.iterrows():
            cid = int(r["cand_id"]); ch = {}
            for c in CHAR:
                src = "volume_mm3" if c == "log_volume_mm3" else c
                v = r.get(src) if src in cand.columns else None
                v = None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
                ch[c] = (float(np.log(max(v, 1.0))) if c == "log_volume_mm3" and v is not None else v)
            rows.append(dict(study=sid, cand_id=cid, math=float(r["score_v4"]) if "score_v4" in cand.columns and not pd.isna(r["score_v4"]) else 0.0,
                             hemi=str(r["hemi"]) if "hemi" in cand.columns else "", pred=pred.get(cid, {}), char=ch, has_maps=cid in maps))
        os.makedirs(os.path.dirname(cz), exist_ok=True)
        with open(cz + ".tmp", "wb") as f_: np.savez_compressed(f_, **{str(k): v for k, v in maps.items()})
        os.replace(cz + ".tmp", cz)                                               # atomic: a reader never sees a half-written cache
        C = dict(key=key, v=3, rows=rows); _js(cj, C)
    with np.load(cz) as Zf: Z = {k: Zf[k] for k in Zf.files}
    rows = []; pat = CTX["patient_of"](sid); test = test_assignment(pat, CTX["SET"].get("percival_test_fraction", 0.2))
    for r in C["rows"]:
        rows.append(dict(r, patient=pat, test=test, maps=Z.get(str(r["cand_id"]))))
    if labelled:
        L, _ = _labels(sid); rows = [dict(r, y=L[r["cand_id"]]) for r in rows if r["cand_id"] in L]
    return rows


# ------------------------------------------------------------------ selection + integrity
def selection():
    S = CTX["SET"]; ex = set(S.get("learner_exclude", [])); arch_ok = S["features"].get("train_include_archived", True); out = []
    from uengine.percival.meta import test_assignment
    for p in CTX["patients"]():
        c = p["code"]; rev = CTX["is_reviewed"](c)
        why = "excluded by you" if c in ex else ("archived (excluded in Settings)" if p.get("archived") and not arch_ok else "")
        out.append(dict(code=c, label=CTX["label"](c), cohort=p.get("cohort", ""), reviewed=rev, archived=bool(p.get("archived")), retired=bool(p.get("retired")),
                        included=rev and not why, excluded_why=why, why="" if rev else "review not finished",
                        partition="test" if test_assignment(CTX["patient_of"](c), S.get("percival_test_fraction", 0.2)) else "development"))
    return out


def set_selection(codes, include):
    S = CTX["SET"]; ex = set(S.get("learner_exclude", []))
    for c in codes: (ex.discard if include else ex.add)(c)
    S["learner_exclude"] = sorted(ex); CTX["save_settings"](); return dict(ok=True, excluded=len(ex))


def integrity(sel):
    rep = dict(studies=len(sel), unused_labels=0, conflicts={}, duplicates=[])
    fps = {}
    for c in sel:
        _, u = _labels(c); rep["unused_labels"] += u
        k = _conflicts(c)
        if k: rep["conflicts"][CTX["label"](c)] = len(k)
        fp = CTX["fingerprint_of"](c)
        if fp:
            if fp in fps: rep["duplicates"].append(c)
            else: fps[fp] = c
    return rep


# ------------------------------------------------------------------ registry
def versions(): return sorted(os.path.basename(d) for d in glob.glob(P("registry", "v*")) if os.path.isdir(d))
_MCACHE = {}
def load(v):
    """registry model (cached by file mtime: the screen polls every few seconds and models with tree ensembles are large)"""
    p = P("registry", v, "model.json")
    try: mt = os.path.getmtime(p)
    except OSError: return None
    c = _MCACHE.get(p)
    if c and c[0] == mt: return c[1]
    m = _jl(p, None)
    if m is not None: _MCACHE[p] = (mt, m)
    return m
def active_version(): return _jl(P("active.json"), {}).get("version")
def active():
    v = active_version(); return load(v) if v else None


def promote(v, by="app user", why="made active by you"):
    if not os.path.exists(P("registry", v, "model.json")): return dict(ok=False, error="unknown version")
    cur = _jl(P("active.json"), {}); prev = cur.get("version")
    if prev == v: prev = cur.get("previous")                 # re-promoting the active version keeps its rollback target (v5.23 fix)
    _js(P("active.json"), dict(version=v, previous=prev, at=time.strftime("%Y-%m-%d %H:%M:%S"), by=by, why=why))
    R = _jl(P("registry", "promotions.json"), []); R.append(dict(version=v, previous=prev, at=time.strftime("%Y-%m-%d %H:%M:%S"), by=by, why=why)); _js(P("registry", "promotions.json"), R)
    threading.Thread(target=score_all, daemon=True).start(); return dict(ok=True, version=v, previous=prev)


def rollback(by="app user"):
    a = _jl(P("active.json"), {})
    if not a.get("previous"): return dict(ok=False, error="no previous version to roll back to")
    return promote(a["previous"], by, "rollback")


# ------------------------------------------------------------------ training cycle
def _env_min():
    v = os.environ.get("CSS_LEARN_MIN", "")
    try: a, b, c = (int(x) for x in v.split(",")); return dict(studies=a, candidates=b, per_class=c)
    except Exception: return None


def train_async(reason="manual"):
    with LOCK:
        if JOB["state"] == "running": return dict(ok=True, already_running=True)
        JOB.update(state="running", log=[], progress=0.0, error="", reason=reason, started=time.time())
    threading.Thread(target=_train, args=(reason,), daemon=True).start(); return dict(ok=True, started=True)


def _train(reason):
    from uengine.percival import meta as MT
    try:
        sel = [s["code"] for s in selection() if s["included"]]
        if not sel: raise ValueError("no finished, selected study to learn from")
        if not all(may_read(c) for c in sel): raise ValueError("local learning is not switched on (Percival Intelligence › Switch on)")
        log(f"cycle started ({reason}): {len(sel)} studies", 0.01); integ = integrity(sel); dup = set(integ["duplicates"]); rows = []
        for k, c in enumerate(sel):
            if c in dup: continue
            r = gather(c, labelled=True); rows += r; log(f"{CTX['label'](c)}: {len(r)} labelled candidates", 0.01 + 0.06 * (k + 1) / len(sel))
        v = f"v{len(versions()) + 1:03d}"
        M = MT.train_cycle(rows, v, cnn_epochs=int(os.environ.get("CSS_PERCIVAL_EPOCHS", "30")), progress=lambda m, p: log(m, p), mins=_env_min())
        M["integrity"] = integ; M["reason"] = reason; act = active(); acc = MT.acceptance(M, act); M["acceptance"] = acc
        M["previous_active"] = act["version"] if act else None
        _js(P("registry", v, "model.json"), M)
        H = _jl(P("history.json"), []); t = M["test"]
        H.append(dict(version=v, at=M["created"], reason=reason, studies=M["data"]["studies"], candidates=M["data"]["dev_candidates"] + M["data"]["test_candidates"],
                      css=M["data"]["css"], chosen=M["discovery"]["chosen"], dev={k: (x or {}).get("auc") for k, x in M["discovery"]["results"].items()},
                      test_auc=(t.get("percival") or {}).get("auc"), test_ci=(t.get("percival") or {}).get("auc_ci"), test_math_auc=(t.get("math") or {}).get("auc"),
                      passed=acc["passed"], promoted=False))
        if acc["passed"] or (act is None and os.environ.get("CSS_PERCIVAL_FIRST_ACTIVE") == "1"):
            promote(v, by=f"automatic ({reason})", why="passed the acceptance criteria" if acc["passed"] else "first model (test setting)"); H[-1]["promoted"] = True
            log(f"{v} promoted: {'passed the acceptance criteria' if acc['passed'] else 'first model'}", 0.95)
        else: log(f"{v} kept as a candidate: {'; '.join(acc['reasons'])}", 0.95)
        _js(P("history.json"), H); _js(P("last_cycle.json"), dict(at=time.strftime("%Y-%m-%d %H:%M:%S"), finished=sorted(sel)))
        CTX["notify"](f"Percival Score model {v} trained", ("promoted" if H[-1]["promoted"] else "kept as a candidate") + f" · {M['data']['studies']} studies")
        with LOCK: JOB.update(state="finished", progress=1.0)
    except Exception as e:
        with LOCK: JOB.update(state="failed", error=f"{type(e).__name__}: {str(e)[:300]}")
        log(f"failed: {e}")


def maybe_cycle():
    """controlled cycles: a new training cycle when N newly finished studies have accumulated since the last cycle"""
    S = CTX["SET"]
    if not S.get("percival_autocycle", True) or not authorized() or JOB["state"] == "running": return False
    done = {s["code"] for s in selection() if s["included"]}; last = set(_jl(P("last_cycle.json"), {}).get("finished", []))
    if len(done - last) >= int(S.get("percival_cycle_n", 5)): train_async(f"{len(done - last)} newly finished studies"); return True
    return False


# ------------------------------------------------------------------ scoring + prediction ledger
def _run_id(sid):
    a = _jl(os.path.join(B(), "runs", sid, "active.json"), {}); return a.get("run_id") or "initial"


def score_study(sid, M=None):
    from uengine.percival import meta as MT
    M = M or active()
    if not M: return None
    rows = gather(sid, labelled=False)
    if not rows: return None
    S = MT.score_rows(M, rows); hemi = {r["cand_id"]: r.get("hemi", "") for r in rows}
    for s in S: s["hemi"] = hemi.get(s["cand_id"], "")
    ids = [s["cand_id"] for s in S if s["percival_score"] is not None and s["percival_score"] >= 50]
    study = dict(n_called=len(ids), called_ids=ids, L_score=None, R_score=None, total=None, error="")
    try:                                                   # the study score with the reader's own scoring method, on the candidates Percival calls
        r = subprocess.run([sys.executable, os.path.join(CTX["SC"], "score_css.py"), sid, "--accept-ids", ",".join(map(str, ids)) or "none", "--tag", "percival"],
                           capture_output=True, text=True, timeout=600, env=dict(os.environ, CSS_BASE=B(), PYTHONWARNINGS="ignore"))
        J = _jl(os.path.join(B(), "review", f"{sid}_score_percival.json"), {})
        study.update(L_score=J.get("L_score"), R_score=J.get("R_score"), total=J.get("multifocality_0_4"), error="" if r.returncode == 0 else (r.stderr or r.stdout)[-160:])
    except Exception as e: study["error"] = type(e).__name__
    in_tr = sid in set((M.get("data") or {}).get("trained_on") or [])
    rec = dict(study=sid, model=M["version"], run=_run_id(sid), created=time.strftime("%Y-%m-%d %H:%M:%S"), ready=M["ready"], thresholds=M["thresholds"],
               in_training=in_tr, in_training_note="this study's expert labels were used to train this model: its scores are in-sample (optimistic)" if in_tr else "",
               candidates=S, study_score=study, note=M["note"], kind="AI prediction (Percival Score) - not a human review")
    lp = P("ledger", sid, f"{M['version']}__{rec['run']}.json")
    if not os.path.exists(lp): _js(lp, rec)                     # immutable: a later model writes a NEW file
    _js(P("scores", f"{sid}.json"), rec); return rec


def score_all():
    M = active()
    if not M: return
    for p in CTX["patients"]():
        if not p.get("retired") and os.path.exists(os.path.join(B(), "review", f"{p['code']}_candidates.csv")) and may_read(p["code"]):
            try: score_study(p["code"], M)
            except Exception as e: log(f"{CTX['label'](p['code'])}: not scored ({type(e).__name__})")


def history_of(sid):
    return [_jl(f, {}) for f in sorted(glob.glob(P("ledger", sid, "*.json")))]


# ------------------------------------------------------------------ v5.23 expert-review snapshots (the local learning dataset)
def _slug(x):
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", str(x).strip()).strip("_") or "reviewer"


def _sha(p):
    try:
        with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()
    except Exception: return None


def snapshot_study(sid):
    """one IMMUTABLE record per final expert review: labels + exactly what the models said when the review was saved. -> n new"""
    import pandas as pd
    finals = sorted(set(glob.glob(os.path.join(B(), "review", f"{sid}_final_*.json"))) | set(glob.glob(os.path.join(B(), "review", f"{sid}_final.json"))))
    new = 0; cand = None
    for fp in finals:
        F = _jl(fp, {}); rev, saved = F.get("reviewer"), F.get("saved")
        if not rev or not saved: continue
        out = P("reviews", sid, f"{_slug(rev)}__{_slug(saved)}.json")
        if os.path.exists(out): continue                                     # immutable: never rewritten
        cp = os.path.join(B(), "review", f"{sid}_calls_{_slug(rev)}.csv")
        if not os.path.exists(cp): cp = os.path.join(B(), "review", f"{sid}_calls.csv")
        labels = pd.read_csv(cp, dtype=str).fillna("").to_dict("records") if os.path.exists(cp) else []
        shown = None                                                          # the newest Percival prediction that existed when the review was saved
        for L in history_of(sid):
            if L.get("created") and L["created"] <= saved and (shown is None or L["created"] >= shown["created"]): shown = L
        if cand is None:
            from uengine.percival.meta import CHAR
            cand = []; rows = {}
            try: rows = {r["cand_id"]: r for r in gather(sid, labelled=False)}
            except Exception as e: log(f"{CTX['label'](sid)}: review snapshot without measurements ({type(e).__name__})")
            cpath = os.path.join(B(), "review", f"{sid}_candidates.csv")
            if os.path.exists(cpath):
                d = pd.read_csv(cpath)
                for _, r in d.iterrows():
                    cid = int(r["cand_id"]); g = rows.get(cid, {}); mp = g.get("maps")
                    cand.append(dict(cand_id=cid, hemi=str(r.get("hemi", "")), region=str(r.get("region", "")),
                                     vox=[int(r[k]) for k in ("vox_i", "vox_j", "vox_k") if k in d.columns and not pd.isna(r[k])],
                                     volume_mm3=None if pd.isna(r.get("volume_mm3", np.nan)) else float(r["volume_mm3"]), math=g.get("math"), char=g.get("char"), predictors=g.get("pred"),
                                     patch_sha256=None if mp is None else hashlib.sha256(np.ascontiguousarray(mp, np.float32).tobytes()).hexdigest()[:16],
                                     patch_reference=f"unified_engine/percival/cache/{sid}.npz#{cid}" if mp is not None else None))
        rec = dict(schema="percival-review-snapshot/1.0", kind="expert review (human) - original label, never overwritten", study=sid, reviewer=rev, saved=saved,
                   read_mode=F.get("read_mode", ""), percival_visible_to_reviewer=F.get("meter_visible", ""), labels=labels,
                   percival_at_review=None if shown is None else dict(model=shown.get("model"), created=shown.get("created"), run=shown.get("run"),
                                                                      candidates=shown.get("candidates"), thresholds=shown.get("thresholds")),
                   percival_note="no Percival Score existed for this study when the review was saved" if shown is None else "the newest prediction created before the save",
                   candidates=cand, processing=dict(run=_run_id(sid), manifest_sha256=_sha(os.path.join(B(), "review", f"{sid}_manifest.json")),
                                                    candidates_sha256=_sha(os.path.join(B(), "review", f"{sid}_candidates.csv"))),
                   active_model_at_snapshot=active_version(), snapshot_created=time.strftime("%Y-%m-%d %H:%M:%S"),
                   identifiers="none - the study is named by its internal key")
        _js(out, rec); new += 1
    return new


def snapshot_reviews():
    n = 0
    for p in CTX["patients"]():
        try: n += snapshot_study(p["code"])
        except Exception as e: log(f"{CTX['label'](p['code'])}: review snapshot failed ({type(e).__name__})")
    return n


def reviews_of(sid): return [_jl(f, {}) for f in sorted(glob.glob(P("reviews", sid, "*.json")))]


# ------------------------------------------------------------------ the Percival Intelligence screen
def state():
    from uengine.percival import meta as MT
    with LOCK: job = {k: v for k, v in JOB.items() if k != "log"}; jlog = JOB["log"][-60:]      # job FIRST (v5.23): a cycle finishing while
    vs = versions(); latest = load(vs[-1]) if vs else None; M = active(); sel = selection()      # this runs must not look finished with old versions
    strip = lambda m: None if not m else {k: v for k, v in m.items() if k not in ("components", "meta_ensemble")}
    return dict(authorized=authorized(), autocycle=CTX["SET"].get("percival_autocycle", True), cycle_n=int(CTX["SET"].get("percival_cycle_n", 5)),
                test_fraction=CTX["SET"].get("percival_test_fraction", 0.2), job=job, log=jlog,
                active=strip(M), latest=strip(latest), versions=vs, history=_jl(P("history.json"), []), promotions=_jl(P("registry", "promotions.json"), []),
                selection=sel, n_selected=sum(1 for s in sel if s["included"]),
                minimum=dict(studies=MT.MIN_STUDIES, candidates=MT.MIN_CANDIDATES, per_class=MT.MIN_PER_CLASS),
                since_last=len({s["code"] for s in sel if s["included"]} - set(_jl(P("last_cycle.json"), {}).get("finished", []))),
                n_review_snapshots=len(glob.glob(P("reviews", "*", "*.json"))))
