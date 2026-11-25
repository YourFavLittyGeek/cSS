"""User-controlled study selection, training gate and study status (v5.14.2-rc4; sketches v2/v3 approved 2026-11-20).

Files, all in the experimental project's app_data/split/ (local only):
  v<N>.json      every applied selection, never overwritten or deleted (history; any version can be restored as a new version)
  current.json   the selection in force (a copy of the latest version); read by uscore.common.Cohort
  gate.json      training gate {open, at, by}; uscore.pipeline.train refuses while it is closed (app and command line alike)
  spent.json     test studies already used for a held-out evaluation (written by uscore.pipeline.evaluate_heldout)
Roles: train (learns from it) | test (held out, labels locked) | hold (temporarily out of training) | exclude (no part; reason required).
Nothing here reads reader calls' VALUES except to count calls (n, cSS) for display and to fingerprint the calls file."""
import os, json, glob, time, hashlib, csv

ROLES = ("train", "test", "hold", "exclude")
MAN_ROLE = {"development": "train", "held-out": "test"}
PRED = ("x1_vessel_continuity_mm", "x2_core_contrast_nu", "x3_pial_distance_mm", "x4_sulcal_alignment", "x5_extracranial_mm")


def _d(B): return os.path.join(B, "app_data", "split")
def _jl(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d
def _js(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True); t = p + ".tmp"
    with open(t, "w") as f: json.dump(d, f, indent=1)
    os.replace(t, p)
_SHA = {}
def _sha(p):
    st = os.stat(p); k = (p, st.st_size, st.st_mtime)
    if k in _SHA: return _SHA[k]
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    _SHA[k] = h.hexdigest(); return _SHA[k]


def current(B): return _jl(os.path.join(_d(B), "current.json"), None)
def versions(B):
    out = []
    for p in sorted(glob.glob(os.path.join(_d(B), "v*.json")), key=lambda x: int(os.path.basename(x)[1:-5])):
        v = _jl(p, {}); out.append(dict(version=v.get("version"), at=v.get("at"), by=v.get("by"), note=v.get("note", ""), changes=v.get("changes", {})))
    return out


def gate(B):
    g = _jl(os.path.join(_d(B), "gate.json"))
    return g if g is not None else dict(open=True, configured=False, note="not configured yet: training allowed (legacy); close it to block training")
def set_gate(B, open_, by):
    g = dict(open=bool(open_), at=time.strftime("%Y-%m-%d %H:%M:%S"), by=by or "user", configured=True)
    _js(os.path.join(_d(B), "gate.json"), g); return g


def manifest_rows(B):
    demo = os.environ.get("CSS_USCORE_DEMO") == "1" and os.environ.get("CSS_USCORE_MANIFEST")      # synthetic demo / tests only
    for p in ((demo,) if demo else (os.path.join(B, "unified_score", "cohort_manifest_RECONCILED.csv"),)):
        if os.path.exists(p): return {r["study_id"]: r for r in csv.DictReader(open(p))}
    return {}


def effective_roles(B, studies):
    """role per study: the user's selection if it lists the study, else the manifest role (development -> train, held-out -> test)"""
    cur = current(B) or {}; man = manifest_rows(B); out = {}
    for s in studies:
        if s in (cur.get("roles") or {}): out[s] = cur["roles"][s]
        else:
            r = man.get(s); out[s] = MAN_ROLE.get(r["role"], "exclude") if r and r.get("decision") == "include" else ("exclude" if r else "hold")   # new study: not assigned yet
    return out


def _calls(B, s):
    p = os.path.join(B, "review", f"{s}_calls.csv")
    if not os.path.exists(p): return None
    try:
        rows = list(csv.DictReader(open(p)))
        c = [str(r.get("call", "")).strip() for r in rows]
        return dict(n=sum(1 for x in c if x), css=sum(1 for x in c if x.lower() == "css"), sha=_sha(p))
    except Exception: return None


def _n_candidates(B, s):
    p = os.path.join(B, "review", f"{s}_candidates.csv")
    if not os.path.exists(p): return None
    try: return max(0, sum(1 for _ in open(p)) - 1)
    except Exception: return None


def _models(B):
    out = []
    for name, p in (("trained", os.path.join(B, "uscore", "model_trained.json")), ("frozen", os.path.join(B, "uscore", "model_frozen.json"))):
        m = _jl(p)
        if m: out.append(dict(kind=name, hash=m.get("model_hash", "")[:8], at=time.strftime("%d %b %H:%M", time.localtime(os.path.getmtime(p))),
                              fp=m.get("label_fingerprints") or {}, train=m.get("train_studies") or [], split=m.get("split_version")))
    return out


def status(B, studies, cohort_of=None):
    """one row per study: role, labels (status), calls, features, recommendation"""
    cur = current(B) or {}; roles = effective_roles(B, studies); reasons = cur.get("reasons") or {}; keys = cur.get("patient") or {}
    spent = _jl(os.path.join(_d(B), "spent.json"), {}) or {}; models = _models(B)
    swi = {}
    for s in studies:
        p = next((q for q in (f"{B}/data/{s}_swi.nii", f"{B}/data/{s}_swi.nii.gz") if os.path.exists(q)), None)
        if p:
            st = os.stat(p); swi[s] = (st.st_size, _sha(p))
        else:                                       # 2026-11-25: moved to Pensieve -> the SHA-256 recorded at the move
            try:
                import pensieve_move as _PMV
                mf = _PMV.marker_file(B, s, f"data/{s}_swi.nii") or _PMV.marker_file(B, s, f"data/{s}_swi.nii.gz")
                if mf: swi[s] = (mf["size"], mf["sha256"])
            except ImportError: pass
    by_sha = {}
    for s, (_, h) in swi.items(): by_sha.setdefault(h, []).append(s)
    rows = []
    for s in studies:
        role = roles[s]; c = _calls(B, s); ncand = _n_candidates(B, s)
        F = _jl(os.path.join(B, "uscore", "features", f"{s}.json"))
        labels, rec = [], None
        for m in models:
            if s in m["fp"]:
                labels.append(dict(kind="trained", text=f"trained on · model {m['hash']} ({m['kind']}, {m['at']})"))
                if role == "train" and c and m["fp"][s] and c["sha"] != m["fp"][s]:
                    labels.append(dict(kind="stale", text=f"calls changed after training ({m['kind']} model {m['hash']})"))
                elif role == "train" and m["fp"][s] and not c:
                    labels.append(dict(kind="stale", text=f"calls removed after training ({m['kind']} model {m['hash']})"))
        if role == "test":
            labels.append(dict(kind="spent" if s in spent else "test", text=f"test · evaluated {len(spent[s])}× (spent)" if s in spent else "test · never evaluated"))
        elif s in spent: labels.append(dict(kind="spent", text="was test · evaluated (spent)"))
        if role == "hold": labels.append(dict(kind="hold", text="on hold" + (f": {reasons.get(s)}" if reasons.get(s) else "")))
        if role == "exclude": labels.append(dict(kind="exclude", text="excluded" + (f": {reasons.get(s)}" if reasons.get(s) else "")))
        if role == "train" and not c: labels.append(dict(kind="unread", text="not reviewed – contributes nothing"))
        # recommendations (never applied automatically)
        qc = _jl(os.path.join(B, "review", f"{s}_qc.json"), {}) or {}
        why_x = []
        if qc.get("registration_ok") is False: why_x.append("registration rejected by QC: anatomy-based predictors measure the wrong place")
        if qc.get("status") == "insufficient_quality": why_x.append("QC: insufficient image quality")
        if s in swi and len(by_sha[swi[s][1]]) > 1 and sorted(by_sha[swi[s][1]])[0] != s:
            why_x.append(f"identical SWI to {sorted(by_sha[swi[s][1]])[0]} (duplicate export)")
        if ncand is None and role in ("train", "test"): why_x.append("no detection output for this study")
        if F and F.get("records"):
            tot = bad = 0
            for r in F["records"]:
                for k in PRED:
                    st_ = ((r.get("F") or {}).get(k) or {}).get("status")
                    if st_: tot += 1; bad += st_ != "reliable"
            if tot and bad / tot >= 0.8: why_x.append(f"{round(100 * bad / tot)} % of predictor values unreliable / unavailable")
        if why_x and role != "exclude": rec = dict(kind="exclude", why="; ".join(why_x))
        elif role == "train" and c and ncand and c["n"] / max(ncand, 1) < 0.5:
            rec = dict(kind="hold", why=f"reads incomplete ({c['n']} of {ncand} candidates called): hold until finished")
        rows.append(dict(study=s, cohort=(cohort_of or {}).get(s, ""), role=role, reason=reasons.get(s, ""), patient=keys.get(s, ""),
                         calls=c["n"] if c else None, css=c["css"] if c else None, candidates=ncand, features=bool(F), labels=labels, recommendation=rec))
    # same patient on both sides (train vs test)
    side = {}
    for r in rows:
        if r["patient"] and r["role"] in ("train", "test"): side.setdefault(r["patient"], set()).add(r["role"])
    for r in rows:
        if r["patient"] and side.get(r["patient"]) == {"train", "test"}:
            other = [x["study"] for x in rows if x["patient"] == r["patient"] and x["study"] != r["study"]]
            r["labels"].append(dict(kind="conflict", text=f"same patient as {', '.join(other)} on the other side"))
            if r["role"] == "test" or not r["recommendation"]:
                r["recommendation"] = dict(kind="exclude", why=f"same patient as {', '.join(other)} (other side) - or move both to the same side")
    return dict(rows=rows, version=cur.get("version"), gate=gate(B), models=[{k: v for k, v in m.items() if k != "fp"} for m in models])


def conflicts(roles, keys):
    side = {}
    for s, r in roles.items():
        k = keys.get(s)
        if k and r in ("train", "test"): side.setdefault(k, {}).setdefault(r, []).append(s)
    return [(k, v["train"], v["test"]) for k, v in side.items() if "train" in v and "test" in v]


def apply(B, studies, changes, by, note="", confirm_spent=False):
    """changes = {study: {role?, reason?, patient?}} -> new version. Refused (nothing written) on: unknown role, exclude / hold
    without a reason, a spent test study moved to train without confirm_spent, the same patient on both sides."""
    cur = current(B) or {}
    roles = dict(effective_roles(B, studies)); roles.update(cur.get("roles") or {})
    reasons = dict(cur.get("reasons") or {}); keys = dict(cur.get("patient") or {})
    spent = _jl(os.path.join(_d(B), "spent.json"), {}) or {}; errs = []; diff = {}
    for s, ch in changes.items():
        if "patient" in ch: keys[s] = str(ch["patient"]).strip()[:32]
        if "role" in ch:
            r = ch["role"]
            if r not in ROLES: errs.append(f"{s}: unknown role {r}"); continue
            if r in ("exclude", "hold") and not (ch.get("reason") or reasons.get(s)): errs.append(f"{s}: a reason is required for {r}")
            if r == "train" and roles.get(s) == "test" and s in spent and not confirm_spent:
                errs.append(f"{s}: spent test study (already used to evaluate a model) - moving it to train needs your typed confirmation")
            if roles.get(s) != r: diff[s] = f"{roles.get(s)} -> {r}"
            roles[s] = r
        if ch.get("reason"): reasons[s] = str(ch["reason"])[:200]
    for k, tr, te in conflicts(roles, keys):
        errs.append(f"patient {k} on both sides: train {', '.join(tr)} / test {', '.join(te)} - move them to the same side")
    if errs: return dict(ok=False, errors=errs)
    n = max([v["version"] or 0 for v in versions(B)] + [0]) + 1
    doc = dict(version=n, at=time.strftime("%Y-%m-%d %H:%M:%S"), by=by or "user", note=note, roles=roles, reasons=reasons, patient=keys, changes=diff,
               parent=cur.get("version"))
    _js(os.path.join(_d(B), f"v{n}.json"), doc); _js(os.path.join(_d(B), "current.json"), doc)
    return dict(ok=True, version=n, changes=diff)


def restore(B, version, by):
    v = _jl(os.path.join(_d(B), f"v{int(version)}.json"))
    if not v: return dict(ok=False, errors=[f"no split version {version}"])
    n = max([x["version"] or 0 for x in versions(B)] + [0]) + 1
    doc = dict(v, version=n, at=time.strftime("%Y-%m-%d %H:%M:%S"), by=by or "user", note=f"restored from v{version}", parent=(current(B) or {}).get("version"), changes={})
    _js(os.path.join(_d(B), f"v{n}.json"), doc); _js(os.path.join(_d(B), "current.json"), doc)
    return dict(ok=True, version=n)


def pending_training(B, studies):
    """train studies whose calls are new or changed since the latest trained model (for auto-train and the notification)"""
    roles = effective_roles(B, studies); ms = _models(B); fp = ms[0]["fp"] if ms else {}; out = []
    for s in studies:
        if roles.get(s) != "train": continue
        c = _calls(B, s)
        if c and fp.get(s) != c["sha"]: out.append(s)
    return out
