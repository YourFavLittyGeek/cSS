"""common.py - versions, cohort guards, label-access control and registration state for the unified cSS score.
EXPERIMENTAL research software. Not for clinical use. No output is a diagnosis."""
import os, csv, json, hashlib, datetime, platform

FEATURE_VERSION = "uscore-features/1.0"
MODEL_VERSION = "uscore-model/1.0"
DETECTOR_VERSION = "uscore-detectors/1.0"
DECISION_VERSION = "uscore-decision/1.0"
PREDICTORS = ["x1_vessel_continuity_mm", "x2_core_contrast_nu", "x3_pial_distance_mm", "x4_sulcal_alignment", "x5_extracranial_mm"]
FALLBACK_DROP_ORDER = ["x4_sulcal_alignment", "x5_extracranial_mm"]   # predeclared (design section 3)
SUPPRESSION_ENABLED = False      # hard default; see decision.py. Never changed by configuration in this stage.

HERE = os.path.dirname(os.path.abspath(__file__)); US = os.path.dirname(HERE)
DEFAULT_MANIFEST = os.path.join(US, "cohort_manifest_RECONCILED.csv")


class CohortError(RuntimeError): pass
class HeldOutAccessError(RuntimeError): pass


def sha256_file(p, n=None):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read() if n is None else f.read(n))
    return h.hexdigest()


def versions():
    import numpy, scipy
    return dict(feature=FEATURE_VERSION, model=MODEL_VERSION, detector=DETECTOR_VERSION, decision=DECISION_VERSION,
                numpy=numpy.__version__, scipy=scipy.__version__, python=platform.python_version())


class Cohort:
    """Manifest-backed cohort. eligible_prefix is 'M' for real use. The synthetic test mode (prefix 'SYN') exists only so the
    automated tests can exercise the pipeline; every output it produces is stamped SYNTHETIC TEST."""
    def __init__(self, manifest=DEFAULT_MANIFEST, eligible_prefix="M", synthetic_test=False):
        if eligible_prefix != "M" and not synthetic_test:
            raise CohortError("only M studies are eligible; another prefix needs synthetic_test=True (tests only)")
        if synthetic_test and eligible_prefix == "M":
            raise CohortError("synthetic test mode may not use the M prefix (name collision with real patients)")
        self.prefix, self.synthetic = eligible_prefix, synthetic_test
        self.rows = {r["study_id"]: r for r in csv.DictReader(open(manifest))}
        self.manifest, self.manifest_sha = manifest, sha256_file(manifest)
        for i, r in self.rows.items():
            if r["decision"] == "include" and not i.startswith(self.prefix):
                raise CohortError(f"manifest includes non-eligible study {i}")
            if r["decision"] == "include" and r["role"] not in ("development", "held-out"):
                raise CohortError(f"included study {i} has no approved role")

    def role(self, sid):
        if not sid.startswith(self.prefix):
            raise CohortError(f"{sid}: not an eligible study (identifier must start with {self.prefix})")
        r = self.rows.get(sid)
        if r is None: raise CohortError(f"{sid}: not in the manifest")
        if r["decision"] != "include": raise CohortError(f"{sid}: excluded in the manifest ({r['exclusion_reason']})")
        return r["role"]

    def studies(self, role):
        return sorted(i for i, r in self.rows.items() if r["decision"] == "include" and r["role"] == role)

    def check_fit_set(self, sids):
        """Raises unless every study is an eligible DEVELOPMENT study (used before any model fitting)."""
        bad = [s for s in sids if self.role(s) != "development"]
        if bad: raise CohortError(f"model fitting refused: non-development studies {bad}")


class LabelAccess:
    """The only way the engine reads reader labels. Development mode: development studies only. Held-out labels can be read
    only in mode 'heldout_evaluation' with a frozen model whose hash is given and matches. Every access is logged."""
    def __init__(self, cohort, base, mode="development", frozen_model=None, frozen_hash=None, log_dir=None):
        self.c, self.base, self.mode = cohort, base, mode
        self.log = os.path.join(log_dir or os.path.join(base, "uscore"), "label_access_log.csv")
        if mode not in ("development", "heldout_evaluation"): raise HeldOutAccessError(f"unknown mode {mode}")
        if mode == "heldout_evaluation":
            if not frozen_model or not os.path.exists(frozen_model): raise HeldOutAccessError("held-out evaluation needs a frozen model file")
            m = json.load(open(frozen_model))
            if not m.get("frozen") or m.get("model_hash") != frozen_hash:
                raise HeldOutAccessError("held-out evaluation refused: model not frozen or hash mismatch")
            if set(m.get("train_studies", [])) & set(cohort.studies("held-out")):
                raise HeldOutAccessError("frozen model was trained on held-out studies")

    def _log(self, sid, role, ok):
        os.makedirs(os.path.dirname(self.log), exist_ok=True); new = not os.path.exists(self.log)
        with open(self.log, "a", newline="") as f:
            w = csv.writer(f)
            if new: w.writerow(["time", "study", "role", "mode", "granted"])
            w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), sid, role, self.mode, int(ok)])

    def labels(self, sid, cand_table):
        role = self.c.role(sid)
        ok = (role == "development") or (role == "held-out" and self.mode == "heldout_evaluation")
        self._log(sid, role, ok)
        if not ok: raise HeldOutAccessError(f"{sid} is held-out: labels are not readable in mode '{self.mode}'")
        return read_calls(self.base, sid, cand_table)


def read_calls(base, sid, cand_table):
    """Reader calls -> {cand_id: 1 (cSS) / 0 (non-cSS)}; Unsure / unread / Near ICH are left out (not negatives)."""
    import pandas as pd, sys
    sys.path.insert(0, os.path.join(os.path.dirname(US), "scripts"))
    import css_common
    calls, warn = css_common.load_calls(base, sid, cand_table)
    out = {}
    for k, v in calls.items():
        v = css_common.norm_call(v)
        if v == "cSS": out[k] = 1
        elif v in ("Vessel", "Normal", "Artifact", "Microbleed"): out[k] = 0
    return out, warn


def registration_state(qc):
    """'ok' (label shift <= 0.5 mm, T1 anatomy) / 'marginal' (0.5-1.0) / 'unreliable' (> 1.0) / 'swi_only' / 'unverified'.
    Limits from the synthetic shift test (reconcile/shift_sensitivity.py), PROVISIONAL."""
    if not qc: return "unverified"
    if str(qc.get("anatomy", "")).lower().startswith("swi"): return "swi_only"
    s = qc.get("label_shift_mm")
    if s is None: return "unverified"
    if qc.get("registration_ok") is False: return "unreliable"
    return "ok" if s <= 0.5 else ("marginal" if s <= 1.0 else "unreliable")
