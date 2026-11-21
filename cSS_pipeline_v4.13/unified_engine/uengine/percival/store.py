"""store.py (v5.24) - the Percival data store: where models, predictions, review snapshots, datasets and training history live, its schema
version and its migrations. Everything stays in the project folder on this Mac.

Why (root cause of data "disappearing" after an update): up to v5.23 the store was <project>/unified_engine/percival/, i.e. INSIDE the folder
the launcher overwrites with new engine code on every update. Nothing was deleted (rsync without --delete), but code and data were mixed,
there was no schema version, and a newer app could not tell which format it was reading.

Layout (schema 3):
  <project>/percival/STORE.json        schema version, migration history (from, to, at, app version, backup path)
  <project>/percival/registry/vNNN/    model versions (model.json: components, meta-model, calibration, thresholds, dataset id, metrics)
  <project>/percival/active.json       active model + rollback target;  registry/promotions.json = deployment history
  <project>/percival/ledger/ID/        IMMUTABLE predictions (one file per model version x processing run); scores/ID.json = current
  <project>/percival/reviews/ID/       IMMUTABLE expert-review snapshots
  <project>/percival/datasets/dsNNN.json  versioned training-dataset manifests (eligibility of every labelled candidate, content hash)
  <project>/percival/runs/runNNN.json  every training run (started, finished / failed / interrupted, dataset, version, log)   (schema 4)
  <project>/percival/registry/status.json  model status: experimental / candidate / active / retired / rejected + history      (schema 4)
  <project>/percival/eligibility/current.json  last eligibility evaluation of every called candidate (rules version, time)     (schema 4)
  <project>/percival/cache/            derived feature / image-patch cache (safe to delete: rebuilt from the study files)
  <project>/backups/percival/<time>_schema<N>/   copy of the store taken before every migration
Schemas: 1 = v5.22 (unified_engine/percival), 2 = v5.23 (+ reviews/, model intelligence), 3 = v5.24 (own folder, STORE.json, datasets/),
4 = v5.24 learning engine (runs/, registry/status.json, eligibility/; existing files never rewritten).
A store with a NEWER schema than this app supports is never touched (clear message: install the newer app)."""
import hashlib, json, os, shutil, time

SCHEMA = 4
APP_VERSION = "v5.24"


class StoreError(RuntimeError):
    pass


def root(B): return os.path.join(B, "percival")
def legacy_root(B): return os.path.join(B, "unified_engine", "percival")
def _jl(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d
def _js(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as f: json.dump(o, f, indent=1, default=str)
    os.replace(p + ".tmp", p)
def _now(): return time.strftime("%Y-%m-%d %H:%M:%S")


def _legacy_schema(d):
    """schema of a pre-v5.24 store (no STORE.json): 2 when v5.23 review snapshots or a v5.23 model exist, else 1"""
    if os.path.isdir(os.path.join(d, "reviews")): return 2
    for m in sorted(os.listdir(os.path.join(d, "registry"))) if os.path.isdir(os.path.join(d, "registry")) else []:
        if "5.23" in str((_jl(os.path.join(d, "registry", m, "model.json"), {}) or {}).get("engine", "")): return 2
    return 1


def detect(B):
    """-> dict(schema, where ('project' | 'legacy' | 'none'), path, supported, needs_migration, history)"""
    r, l = root(B), legacy_root(B)
    S = _jl(os.path.join(r, "STORE.json"))
    if S is not None:
        s = int(S.get("schema", 0))
        return dict(schema=s, where="project", path=r, supported=s <= SCHEMA, needs_migration=s < SCHEMA, history=S.get("history", []),
                    legacy_left=os.path.isdir(l))
    if os.path.isdir(l) and os.listdir(l):
        s = _legacy_schema(l)
        return dict(schema=s, where="legacy", path=l, supported=True, needs_migration=True, history=[])
    return dict(schema=0, where="none", path=r, supported=True, needs_migration=True, history=[])


def _files(d):
    out = {}
    for dp, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(dp, f); rel = os.path.relpath(p, d)
            if rel.startswith("cache" + os.sep): continue                       # derived cache: rebuilt, not part of the record
            with open(p, "rb") as fh: out[rel] = hashlib.sha256(fh.read()).hexdigest()
    return out


def _backup(B, src, schema):
    if not os.path.isdir(src) or not os.listdir(src): return ""
    dst = os.path.join(B, "backups", "percival", f"{time.strftime('%Y%m%d_%H%M%S')}_schema{schema}")
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("cache"))
    if _files(dst) != _files(src): raise StoreError(f"backup verification failed ({dst}); nothing was changed")
    return dst


# ------------------------------------------------------------------ migrations (sequential, each from N to N+1)
def _m0_to_3(B, rep):
    os.makedirs(root(B), exist_ok=True); rep.append("new Percival store created")


def _m1_to_2(B, src, rep):
    rep.append("schema 1 -> 2: v5.22 models are read by the v5.23+ engine unchanged (defaults: logistic / CNN / feature fusion); no file rewritten")


def _m2_to_3(B, src, rep):
    """move the store out of the engine code folder: copy to <project>/percival.migrating, verify every file by sha256, then switch;
    the old folder is renamed (not deleted) so an older app version finds nothing half-moved"""
    dst, tmp = root(B), root(B) + ".migrating"
    if src == dst: rep.append("schema 2 -> 3: store already in the project folder"); return
    if os.path.exists(tmp): shutil.rmtree(tmp)
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns("cache"))
    if _files(tmp) != _files(src): shutil.rmtree(tmp); raise StoreError("copy verification failed - the old store was left unchanged")
    if os.path.exists(dst):
        if os.listdir(dst): shutil.rmtree(tmp); raise StoreError(f"{dst} already exists and is not empty - not merged automatically")
        os.rmdir(dst)
    os.replace(tmp, dst)
    moved = src + f".moved_{time.strftime('%Y%m%d_%H%M%S')}"
    os.replace(src, moved)
    with open(os.path.join(moved, "MOVED.txt"), "w") as f:
        f.write(f"This Percival store was moved to {dst} by Percival {APP_VERSION} on {_now()} (copy verified by sha256).\n"
                "This folder is kept as it was; it can be deleted once the new version works.\n")
    rep.append(f"schema 2 -> 3: store moved to {dst} (verified); old folder kept as {os.path.basename(moved)}")


def _m3_to_4(B, rep):
    """add the model-status register and the training-run records, DERIVED from the existing files (nothing existing is rewritten):
    the active model -> active; earlier active models -> retired; others -> candidate (passed acceptance) or experimental;
    every history.json entry -> runs/runNNN.json (kind 'imported from history')."""
    r = root(B); st = os.path.join(r, "registry", "status.json")
    if not os.path.exists(st):
        act = (_jl(os.path.join(r, "active.json"), {}) or {}).get("version")
        was = {p.get("version") for p in (_jl(os.path.join(r, "registry", "promotions.json"), []) or [])}
        S = {}
        for v in sorted(os.listdir(os.path.join(r, "registry"))) if os.path.isdir(os.path.join(r, "registry")) else []:
            m = _jl(os.path.join(r, "registry", v, "model.json"))
            if not v.startswith("v") or m is None: continue
            k = "active" if v == act else "retired" if v in was else "candidate" if (m.get("acceptance") or {}).get("passed") else "experimental"
            S[v] = dict(status=k, at=_now(), by="migration to schema 4", why="derived from active.json / promotions.json / acceptance",
                        history=[dict(status=k, at=_now(), by="migration to schema 4")])
        _js(st, S); rep.append(f"schema 3 -> 4: model status register created for {len(S)} version(s)")
    rd = os.path.join(r, "runs")
    if not os.path.isdir(rd):
        H = _jl(os.path.join(r, "history.json"), []) or []
        for i, h in enumerate(H):
            _js(os.path.join(rd, f"run{i + 1:03d}.json"), dict(id=f"run{i + 1:03d}", kind="imported from history (before schema 4)", state="finished",
                                                              started=h.get("at"), finished=h.get("at"), reason=h.get("reason"), version=h.get("version"),
                                                              dataset=h.get("dataset"), summary=h))
        os.makedirs(rd, exist_ok=True); rep.append(f"schema 3 -> 4: {len(H)} earlier training run(s) recorded from history.json")


def migrate(B):
    """bring the store to SCHEMA. Backup first; any failure leaves the previous store as it was and raises StoreError."""
    D = detect(B)
    if not D["supported"]:
        raise StoreError(f"this project's Percival data has schema {D['schema']}, newer than this app supports ({SCHEMA}). "
                         "Nothing was changed. Install the newer Percival version (or restore a backup from backups/percival/).")
    if not D["needs_migration"]: return dict(ok=True, schema=D["schema"], migrated=False, steps=[])
    rep, frm = [], D["schema"]; backup = ""
    try:
        if D["where"] == "none": _m0_to_3(B, rep); _m3_to_4(B, rep)
        else:
            backup = _backup(B, D["path"], frm)
            if backup: rep.append(f"backup: {backup}")
            s = frm
            if s == 1: _m1_to_2(B, D["path"], rep); s = 2
            if s == 2 and D["where"] == "legacy": _m2_to_3(B, D["path"], rep); s = 3
            if s == 2: s = 3                                         # schema-2 store already in the project folder (not produced by any release)
            if s == 3: _m3_to_4(B, rep); s = 4
    except StoreError: raise
    except Exception as e:
        raise StoreError(f"migration from schema {frm} failed ({type(e).__name__}: {e}). The previous store was left as it was"
                         + (f"; a backup is in {backup}" if backup else "") + ".")
    S = _jl(os.path.join(root(B), "STORE.json"), {}) or {}
    H = S.get("history", []) + [dict(frm=frm, to=SCHEMA, at=_now(), app=APP_VERSION, backup=backup, steps=rep)]
    _js(os.path.join(root(B), "STORE.json"), dict(schema=SCHEMA, created=S.get("created", _now()), history=H,
                                                  note="Percival data store - see uengine/percival/store.py for the layout"))
    return dict(ok=True, schema=SCHEMA, migrated=True, frm=frm, steps=rep, backup=backup)


def backups(B):
    d = os.path.join(B, "backups", "percival")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []
