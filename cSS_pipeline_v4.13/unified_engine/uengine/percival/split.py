"""split.py (Phase 3D) - the ONE authoritative patient-level split for Percival training and evaluation.

Stored in the project's Percival store: percival/split/vNNN.json (one file per split version) + percival/split/current.json (pointer).
  assignment     patient -> 'test' | 'development'; a patient's partition NEVER changes inside a version (locked). Patients met later
                 are added by the version's rule (salted SHA-256 of the patient id < test fraction) and recorded as additions.
  new version    changing the test fraction needs new_version() (typed confirmation + person + reason). Every patient that was 'test' in
                 the previous version stays 'test' (an evaluated test patient is never moved into development); additional patients may
                 become 'test'. Models record the split version they were trained with.
  leakage_audit  run on the dataset before training; training refuses to start when it fails: a patient in both partitions, the same
                 examination (image fingerprint) in both, a study held out by another split tool (study_meta.csv 'test', uscore held-out)
                 used for development, an example without a patient, a label that is not expert ground truth, a candidate listed twice.
The rule is the one meta.test_assignment used (salt 'percival-test-cohort-v1'), so existing assignments are reproduced."""
import hashlib, json, os, threading, time

SCHEMA = "percival-split/1.0"
SALT = "percival-test-cohort-v1"
CONFIRM_NEW = "NEW SPLIT VERSION"
_LOCK = threading.Lock()
EXPERT_SOURCES = ("review", "expert_missed_lesion")


class SplitError(ValueError):
    pass


def _dir(store): return os.path.join(store, "split")


def _jl(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d


def _js(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as f: json.dump(obj, f, indent=1, sort_keys=True, default=str); f.flush(); os.fsync(f.fileno())
    os.replace(p + ".tmp", p)


def rule(patient, fraction, salt=SALT):
    return int(hashlib.sha256((salt + str(patient)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < fraction


def digest(S): return hashlib.sha256(json.dumps(sorted(S["assignment"].items())).encode()).hexdigest()[:16]


def current(store):
    ptr = _jl(os.path.join(_dir(store), "current.json"))
    return _jl(os.path.join(_dir(store), f"{ptr['version']}.json")) if ptr else None


def _versions(store):
    d = _dir(store)
    return sorted(f[:-5] for f in os.listdir(d) if f.startswith("v") and f.endswith(".json")) if os.path.isdir(d) else []


def create(store, fraction, by, reason, patients=(), carry_test=()):
    """a new LOCKED split version (internal; first use or new_version)"""
    if not 0.05 <= float(fraction) <= 0.5: raise SplitError("test fraction must be between 0.05 and 0.5")
    v = f"v{len(_versions(store)) + 1:03d}"
    A = {str(p): "test" for p in carry_test}
    for p in patients:
        A.setdefault(str(p), "test" if rule(p, fraction) else "development")
    S = dict(schema=SCHEMA, version=v, created=time.strftime("%Y-%m-%d %H:%M:%S"), by=by, reason=reason, test_fraction=float(fraction), salt=SALT,
             locked=True, carried_test=sorted(str(p) for p in carry_test), assignment=A, additions=[],
             rule=f"patient is 'test' iff sha256(salt + patient)[:8] / 0xFFFFFFFF < {fraction}; previous test patients stay test")
    S["assignment_sha256"] = digest(S)
    _js(os.path.join(_dir(store), f"{v}.json"), S); _js(os.path.join(_dir(store), "current.json"), dict(version=v, since=S["created"]))
    return S


def partition_of(store, patient, default_fraction=0.2):
    """'test' | 'development' from the authoritative split (created on first use, recorded as such); never changes for a patient"""
    if not patient: return None
    with _LOCK:
        S = current(store) or create(store, default_fraction, "Percival (first use)", "split created automatically at first use")
        p = str(patient)
        if p not in S["assignment"]:
            part = "test" if rule(p, S["test_fraction"], S.get("salt", SALT)) else "development"
            S["assignment"][p] = part; S["additions"].append(dict(patient=p, partition=part, at=time.strftime("%Y-%m-%d %H:%M:%S")))
            S["assignment_sha256"] = digest(S); _js(os.path.join(_dir(store), f"{S['version']}.json"), S)
        return S["assignment"][p]


def new_version(store, fraction, by, reason, confirm):
    if confirm != CONFIRM_NEW: raise PermissionError(f"refused: type exactly '{CONFIRM_NEW}' to confirm")
    if not str(by or "").strip() or not str(reason or "").strip(): raise SplitError("refused: a name and a reason are required")
    with _LOCK:
        old = current(store) or dict(assignment={})
        keep = [p for p, part in old["assignment"].items() if part == "test"]
        return create(store, fraction, str(by).strip(), str(reason).strip(), patients=sorted(old["assignment"]), carry_test=keep)


CONFIRM_BALANCE = "BALANCE TEST GROUP"
BALANCE_SALT = "percival-test-balance-v1"
MIN_DEV_PER_CLASS = 8          # a balance never leaves fewer development patients of a class than this


def balance_plan(store, classes, frozen=(), min_per_class=5):
    """2026-11-26: a BALANCED test group without hand-picking. classes: {patient: 'css' | 'no_css'} from finished expert reviews (patients
    without a finished review are not moved); frozen: patients a registered model was trained on (never moved to test). Every current test
    patient stays test. For each class short of min_per_class, development patients of that class are added in a fixed hash order
    (salted SHA-256, not chosen by anyone) - never below MIN_DEV_PER_CLASS development patients of the class.
    -> dict(add={patient: class}, before, after, short) - nothing is written"""
    S = current(store) or dict(assignment={})
    A = S["assignment"]; fz = {str(p) for p in frozen}
    test = {p for p, part in A.items() if part == "test"}
    out = dict(add={}, before={}, after={}, short={})
    for c in ("css", "no_css"):
        have = sorted(p for p in test if classes.get(p) == c)
        pool = [p for p, k in classes.items() if k == c and p not in test]
        movable = sorted((p for p in pool if p not in fz), key=lambda p: hashlib.sha256((BALANCE_SALT + p).encode()).hexdigest())
        need = max(0, int(min_per_class) - len(have)); room = max(0, len(pool) - MIN_DEV_PER_CLASS)
        pick = movable[:min(need, room)]
        for p in pick: out["add"][p] = c
        out["before"][c] = len(have); out["after"][c] = len(have) + len(pick)
        if len(have) + len(pick) < min_per_class:
            out["short"][c] = (f"{len(have) + len(pick)} of {min_per_class}: only {len(pool)} development patients of this class"
                               + (f", {len(pool) - len(movable)} of them already used to train a model" if len(pool) != len(movable) else ""))
    out["development_after"] = {c: sum(1 for p, k in classes.items() if k == c and p not in test and p not in out["add"]) for c in ("css", "no_css")}
    return out


def balance(store, classes, by, reason, confirm, frozen=(), min_per_class=5):
    """write the balance as a NEW split version (typed confirmation, person, reason); the previous version is kept"""
    if confirm != CONFIRM_BALANCE: raise PermissionError(f"refused: type exactly '{CONFIRM_BALANCE}' to confirm")
    if not str(by or "").strip() or not str(reason or "").strip(): raise SplitError("refused: a name and a reason are required")
    with _LOCK:
        plan = balance_plan(store, classes, frozen, min_per_class)
        if not plan["add"]: raise SplitError("nothing to balance: " + ("; ".join(f"{c}: {w}" for c, w in plan["short"].items()) or "every class already has enough test patients"))
        old = current(store) or dict(assignment={}, test_fraction=0.2)
        keep = [p for p, part in old["assignment"].items() if part == "test"] + list(plan["add"])
        S = create(store, old.get("test_fraction", 0.2), str(by).strip(), str(reason).strip(), patients=sorted(old["assignment"]), carry_test=keep)
        S.update(mode="balanced", balance=dict(added=plan["add"], before=plan["before"], after=plan["after"], short=plan["short"],
                                              min_per_class=int(min_per_class), salt=BALANCE_SALT, frozen=len(set(frozen)),
                                              rule="current test patients stay test; per class short of the minimum, development patients of that class "
                                                   "with a finished expert review and never used for training are added in salted-SHA-256 order"))
        S["assignment_sha256"] = digest(S)
        _js(os.path.join(_dir(store), f"{S['version']}.json"), S)
        return S


def held_out_elsewhere(base):
    """studies other split tools hold out (study_meta.csv split 'test'; uscore study_split held-out roles) - never used for development"""
    out = set()
    p = os.path.join(base, "labels", "study_meta.csv")
    if os.path.exists(p):
        try:
            import pandas as pd
            d = pd.read_csv(p, dtype=str)
            if "split" in d.columns and "study_id" in d.columns: out |= set(d[d.split.str.lower() == "test"].study_id)
        except Exception: pass
    cur = _jl(os.path.join(base, "app_data", "split", "current.json"), {}) or {}
    for k, role in (cur.get("roles") or {}).items():
        if str(role).lower() in ("held_out", "heldout", "test", "held-out"): out.add(k)
    return out


def leakage_audit(examples, fingerprint_of=None, held_out=()):
    """-> dict(passed, errors, checks). examples: dataset examples (study, cand_id, patient, partition, label_source, y)"""
    used = [e for e in examples if e.get("partition") in ("development", "test")]
    errors, by_pat, fps = [], {}, {}
    for e in used: by_pat.setdefault(e.get("patient"), set()).add(e["partition"])
    both = sorted(str(p) for p, s in by_pat.items() if len(s) > 1)
    if both: errors.append(f"patient leakage: {len(both)} patient(s) in both development and test")
    nopat = sorted({e["study"] for e in used if not e.get("patient")})
    if nopat: errors.append(f"{len(nopat)} study(ies) used without a patient identifier")
    if fingerprint_of:
        for st in sorted({e["study"] for e in used}):
            fp = fingerprint_of(st)
            if fp: fps.setdefault(fp, set()).update(e["partition"] for e in used if e["study"] == st)
        dupx = [fp for fp, s in fps.items() if len(s) > 1]
        if dupx: errors.append(f"examination leakage: {len(dupx)} identical examination(s) (image fingerprint) in both partitions")
    ho = sorted({e["study"] for e in used if e["partition"] == "development"} & set(held_out))
    if ho: errors.append(f"{len(ho)} study(ies) held out by another split tool used for development: {', '.join(ho[:5])}")
    notexp = sorted({str(e.get("label_source")) for e in used if e.get("label_source") not in EXPERT_SOURCES})
    if notexp: errors.append(f"labels not from expert review: {notexp}")
    keys = [(e["study"], str(e["cand_id"])) for e in used]; dup = len(keys) - len(set(keys))
    if dup: errors.append(f"{dup} candidate(s) listed twice")
    return dict(passed=not errors, errors=errors, checks=dict(patients=len(by_pat), patients_in_both=len(both), studies=len({e["study"] for e in used}),
                                                              examinations_checked=len(fps), held_out_elsewhere=len(set(held_out)), duplicates=dup,
                                                              audited=time.strftime("%Y-%m-%d %H:%M:%S")))
