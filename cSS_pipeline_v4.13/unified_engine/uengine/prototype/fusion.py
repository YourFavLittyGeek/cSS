"""fusion.py - the Unified Score fusion layer (prototype; SYNTHETIC data only).

Modes (same components, same inputs; only the combination differs):
  offset        logit = MATH logit + learned increment (increment fitted WITH the math logit as offset)   <- proposed design
  math_only     logit = MATH logit
  learned_only  logit = learned model on the characteristics alone (no MATH)
  naive         logit = MATH logit + independently fitted learned-only logit (double counting; ablation only)
  joint         logit = learned model on characteristics + math logit as a free column (no offset)
Uncertainty: n_boot patient-bootstrap refits (recalibration + learned part, penalty fixed at the chosen value) -> per-candidate 5-95 %
interval of the probability. Category (reading aid, never an exclusion):
  likely_cSS      p >= hi and the whole interval above 0.5      unlikely_cSS   p <= lo and the whole interval below 0.5
  uncertain       anything else, and ALWAYS when: an interval straddles 0.5, > max_missing of the 9 measured inputs are missing / corrupt /
                  out of range, an input was clipped to the training range (extrapolation), MATH is inconsistent, registration is not ok
  not_scorable    MATH score unavailable (modes that need MATH) or the object is outside the candidate model (gate-dropped / not generated)
Every result carries a trace: inputs used, statuses, MATH source and recalibration, learned intercept and per-feature contributions,
final logit, interval, the category rules that fired, model hash and versions."""
import hashlib, json, datetime
from dataclasses import dataclass
import numpy as np
from .. import __version__ as PKG_VERSION, provenance as pv, feature_schema as fs
from ..ml_component import sigmoid, PenalizedLogistic, Preprocessor, MathRecalibration
from . import PROTOTYPE_VERSION
from .inputs import sanitize, InputError
from ..data_validation import assert_predictors_allowed, LeakageError  # noqa: F401
from .components import MathComponent, CharacteristicsComponent, IncrementComponent, NullPastExperience

MODES = ("offset", "math_only", "learned_only", "naive", "joint")
DEFAULT_THRESHOLDS = dict(lo=0.3, hi=0.7, max_missing=2, q=(0.05, 0.95))
NOT_OK_REGISTRATION = ("unreliable", "failed", "unverified", "marginal", "swi_only")


@dataclass
class CandidateResult:
    cand_key: str
    patient_key: str
    exam_id: str
    math: dict
    characteristics: dict
    learned: dict
    unified: dict
    quality_flags: list
    trace: dict


def schema_hash(columns):
    return hashlib.sha256(json.dumps(dict(columns=list(columns), transforms=sorted(fs.TRANSFORMS), indicators=fs.INITIAL_INDICATORS,
                                          schema=[(c.name, c.role, c.lo, c.hi, c.missing) for c in fs.SCHEMA.values()]),
                                     sort_keys=True, default=str).encode()).hexdigest()


def _pl_params(m): return None if m is None else dict(columns=m.columns, lam=m.lam, beta=m.beta.tolist(), median=m.pre.median.tolist(),
                                                     mean=m.pre.mean.tolist(), sd=m.pre.sd.tolist(), cw=m.class_weight)


def _pl_from(p):
    if p is None: return None
    m = PenalizedLogistic(p["columns"], lam=p["lam"], beta=np.array(p["beta"]), class_weight=p["cw"])
    m.pre = Preprocessor(np.array(p["median"]), np.array(p["mean"]), np.array(p["sd"])); return m


class UnifiedScorer:
    def __init__(self, mode="offset", columns=fs.INITIAL_COLUMNS, n_boot=30, seed=0, thresholds=None, math=None, characteristics=None, past=None):
        if mode not in MODES: raise ValueError(f"mode {mode!r} not in {MODES}")
        assert_predictors_allowed(columns)                     # ids / labels / scores / model outputs can never be learned inputs
        self.mode, self.columns, self.n_boot, self.seed = mode, list(columns), int(n_boot), int(seed)
        self.th = dict(DEFAULT_THRESHOLDS, **(thresholds or {}))
        self.math = math or MathComponent()
        self.chars = characteristics or CharacteristicsComponent(self.columns)
        self.past = past or (NullPastExperience() if mode == "math_only" else
                             IncrementComponent(self.columns, offset=(mode == "offset"), joint=(mode == "joint")))
        self.boot = []; self.fit_info = {}; self.model_hash = None

    # ---------------- helpers
    @property
    def needs_math(self): return self.mode in ("offset", "math_only", "naive", "joint")

    def _rows(self, d): return d.to_dict("records")

    def _matrix(self, d, rep):
        outs, X = [], []
        for r in self._rows(d):
            st = {c: s for (k, c), s in rep.status.items() if k == r["cand_key"]}
            o, x = self.chars.outputs(r, st); outs.append(o); X.append(x)
        return outs, np.array(X, float).reshape(len(outs), len(self.columns))

    def _logit(self, X, ml, past_model=None):
        """unified logit for every row; ml = math logit (NaN where not scorable)"""
        if self.mode == "math_only": return ml, np.zeros(len(X)), np.zeros((len(X), 0)), 0.0
        if self.mode == "offset":
            inc, con, b0 = self.past.increment(X, model=past_model); return ml + inc, inc, con, b0
        if self.mode == "learned_only":
            inc, con, b0 = self.past.increment(X, model=past_model); return inc, inc, con, b0
        if self.mode == "naive":
            inc, con, b0 = self.past.increment(X, model=past_model); return ml + inc, inc, con, b0
        inc, con, b0 = self.past.increment(X, np.nan_to_num(ml), model=past_model)          # joint
        return inc, inc, con, b0

    # ---------------- fit
    def fit(self, df, y, data_kind="synthetic", protected=None):
        d, rep = sanitize(df, data_kind=data_kind)
        if protected is not None and set(d.patient_key.astype(str)) & set(protected.patients):
            raise LeakageError("training rows include protected test patients")
        y = np.asarray(y, float)
        if len(y) != len(d): raise InputError("labels and rows differ in length")
        if not np.isin(y, (0.0, 1.0)).all(): raise InputError("training labels must be 0 / 1 on every row (unlabelled rows must be removed)")
        if "measurement_complete" in d.columns and not d.measurement_complete.fillna(False).astype(bool).all():
            raise InputError("gate-dropped / incomplete objects cannot train the candidate model")
        pats = d.patient_key.astype(str).to_numpy()
        M = [self.math.outputs(r) for r in self._rows(d)]; s = np.array([m["score_v4"] for m in M], float)
        use = np.isfinite(s) if self.needs_math else np.ones(len(d), bool)
        if len(set(pats[use])) < 3 or len(np.unique(y[use])) < 2: raise InputError("need >= 3 patients and both classes among scorable rows")
        if self.needs_math: self.math.fit(s[use], y[use])
        _, X0 = self._matrix(d, rep); self.chars.fit(X0[use]); _, X = self._matrix(d, rep)
        ml = self.math.recal.logit(s) if self.needs_math else np.zeros(len(d))
        if self.mode == "math_only": pass
        elif self.mode in ("offset", "joint"): self.past.fit(X[use], y[use], pats[use], np.nan_to_num(ml[use]), seed=self.seed)
        else: self.past.fit(X[use], y[use], pats[use], None, seed=self.seed)           # learned_only, naive: no math in the fit
        rng = np.random.default_rng(self.seed); P = np.array(sorted(set(pats[use]))); idx = {p: np.where(use & (pats == p))[0] for p in P}
        self.boot = []
        for b in range(self.n_boot):
            sel = np.concatenate([idx[p] for p in rng.choice(P, len(P), replace=True)])
            if len(np.unique(y[sel])) < 2: continue
            rc = MathRecalibration().fit(s[sel], y[sel]) if self.needs_math else None
            mlb = rc.logit(s[sel]) if rc is not None else None
            pm = None
            if self.mode != "math_only":
                lam = self.past.m.lam
                pm = self.past.refit(X[sel], y[sel], None if self.mode in ("learned_only", "naive") else np.nan_to_num(mlb), lam)
            self.boot.append((None if rc is None else (rc.a, rc.b), pm))
        self.fit_info = dict(n_rows=int(len(d)), n_used=int(use.sum()), n_not_scorable=int((~use).sum()), n_patients=int(len(P)),
                             n_events=int(y[use].sum()), patients_sha256=hashlib.sha256(json.dumps(sorted(P.tolist())).encode()).hexdigest(),
                             data_kind=data_kind, fitted_at=datetime.datetime.now().isoformat(timespec="seconds"), n_boot_kept=len(self.boot),
                             input_report=dict(corrupt=rep.corrupt, out_of_range=rep.out_of_range, missing_columns=rep.missing_columns))
        self.model_hash = hashlib.sha256(json.dumps(self.params(), sort_keys=True, default=str).encode()).hexdigest()
        return self

    def params(self):
        return dict(prototype=PROTOTYPE_VERSION, package=PKG_VERSION, mode=self.mode, columns=self.columns, thresholds=self.th,
                    schema_sha256=schema_hash(self.columns), math=self.math.params(), characteristics=self.chars.params(),
                    past=self.past.params(), n_boot=self.n_boot, seed=self.seed,
                    boot=[dict(recal=r, past=_pl_params(m)) for r, m in self.boot],
                    training={k: v for k, v in self.fit_info.items() if k not in ("fitted_at",)})

    # ---------------- predict
    def predict(self, df, data_kind="synthetic"):
        if self.model_hash is None: raise RuntimeError("model not fitted")
        d, rep = sanitize(df, data_kind=data_kind)
        M = [self.math.outputs(r) for r in self._rows(d)]; s = np.array([m["score_v4"] for m in M], float)
        C, X = self._matrix(d, rep); ml = np.array([m["logit"] for m in M], float)
        L, inc, con, b0 = self._logit(X, ml)
        if self.boot:
            PB = []
            for rcp, pm in self.boot:
                mlb = (rcp[0] + rcp[1] * np.log(np.clip(s, 0, None) + self.math.recal.eps)) if rcp is not None else ml
                PB.append(sigmoid(self._logit(X, mlb, past_model=pm)[0]))
            PB = np.array(PB); qlo = np.full(len(d), np.nan); qhi = np.full(len(d), np.nan); ok = np.isfinite(PB).any(0)   # unscorable rows: no interval
            if ok.any(): qlo[ok], qhi[ok] = np.nanquantile(PB[:, ok], self.th["q"][0], axis=0), np.nanquantile(PB[:, ok], self.th["q"][1], axis=0)
        else: qlo = qhi = np.full(len(d), np.nan)
        out = []
        for i, r in enumerate(self._rows(d)):
            out.append(self._result(r, M[i], C[i], X[i], L[i], inc[i], con[i] if con.shape[1] else np.zeros(0), b0, qlo[i], qhi[i], rep))
        return out

    def _result(self, r, m, c, x, logit, inc, con, b0, qlo, qhi, rep):
        flags, why = [], []
        reg = str(r.get("registration", "ok") or "ok")
        if reg in NOT_OK_REGISTRATION: flags.append(f"registration {reg}")
        complete = bool(r.get("measurement_complete", True)) if r.get("measurement_complete") is not None else True
        if not complete: flags.append("outside the candidate model (gate-dropped / not generated)")
        if m["status"] == "inconsistent": flags.append("recorded score_v4 disagrees with the verbatim recomputation")
        if m["rule_fate"]: flags.append(f"excluded by MATH rule {m['rule_fate']} (still scored; reading aid only)")
        if c["n_missing_or_invalid"] > self.th["max_missing"]: flags.append(f"{c['n_missing_or_invalid']} of 9 measured inputs missing / invalid")
        if c["extrapolated"]: flags.append("outside the training range (clipped): " + ", ".join(c["extrapolated"]))
        p = float(sigmoid(logit)) if np.isfinite(logit) else np.nan
        if not complete or not np.isfinite(p) or (self.needs_math and not np.isfinite(m["score_v4"])):
            cat = "not_scorable"; why.append("no MATH score" if self.needs_math and not np.isfinite(m["score_v4"]) else "outside the candidate model")
            p = np.nan if not complete else p
        else:
            straddle = np.isfinite(qlo) and qlo <= 0.5 <= qhi
            hard = [f for f in flags if not f.startswith("excluded by MATH rule")]
            if hard: cat = "uncertain"; why.append("quality / input flags")
            elif straddle: cat = "uncertain"; why.append("interval includes 0.5")
            elif p >= self.th["hi"] and (not np.isfinite(qlo) or qlo > 0.5): cat = "likely_cSS"; why.append(f"p >= {self.th['hi']} and interval above 0.5")
            elif p <= self.th["lo"] and (not np.isfinite(qhi) or qhi < 0.5): cat = "unlikely_cSS"; why.append(f"p <= {self.th['lo']} and interval below 0.5")
            else: cat = "uncertain"; why.append(f"p between {self.th['lo']} and {self.th['hi']}")
            if not np.isfinite(qlo): why.append("no bootstrap interval (n_boot = 0)")
        cols = self.past.m.columns if getattr(self.past, "m", None) is not None else []
        contributions = {k: float(v) for k, v in zip(cols, con)}
        calc = dict(offset="p = sigmoid(math_logit + increment)", math_only="p = sigmoid(math_logit)", learned_only="p = sigmoid(increment)",
                    naive="p = sigmoid(math_logit + independent_learned_logit)", joint="p = sigmoid(joint_logit(characteristics, math_logit))")[self.mode]
        trace = dict(model_hash=self.model_hash, prototype=PROTOTYPE_VERSION, package=PKG_VERSION, mode=self.mode, calculation=calc,
                     detector_sha256=pv.DETECTOR_SHA256, schema_sha256=schema_hash(self.columns),
                     math_recalibration=self.math.params()["recal"], math_logit=m["logit"], math_source=m["source"],
                     learned_intercept=float(b0), learned_increment=float(inc), contributions=contributions,
                     inputs_used=dict(zip(self.columns, map(float, x))), input_status=c["status"],
                     input_validation={k2: v for (k1, k2), v in rep.status.items() if k1 == r["cand_key"]},
                     final_logit=float(logit) if np.isfinite(logit) else None, category_rules=why, thresholds=self.th)
        return CandidateResult(str(r["cand_key"]), str(r["patient_key"]), str(r["exam_id"]),
                               dict(score_v4=m["score_v4"], source=m["source"], status=m["status"], logit=m["logit"], rule_fate=m["rule_fate"],
                                    review_tier=m["review_tier"], review_priority_rank=m["review_priority_rank"],
                                    evidence_difference=(m["css_evidence"] - m["vein_evidence"]) if np.isfinite(m["css_evidence"]) and np.isfinite(m["vein_evidence"]) else None),
                               dict(values=c["values"], status=c["status"], n_missing_or_invalid=c["n_missing_or_invalid"]),
                               dict(component=self.past.name, increment=float(inc), intercept=float(b0), contributions=contributions),
                               dict(p=p, p_lo=float(qlo) if np.isfinite(qlo) else None, p_hi=float(qhi) if np.isfinite(qhi) else None,
                                    category=cat, reasons=why), flags, trace)

    # ---------------- persistence
    def save(self, path):
        d = dict(params=self.params(), model_hash=self.model_hash, fitted_at=self.fit_info.get("fitted_at"))
        with open(path, "w") as f: json.dump(d, f, indent=1, default=str)
        return path

    @staticmethod
    def load(path):
        with open(path) as f: d = json.load(f)
        P = d["params"]
        if hashlib.sha256(json.dumps(P, sort_keys=True, default=str).encode()).hexdigest() != d["model_hash"]:
            raise ValueError("model file content does not match its hash (edited or corrupted)")
        if P["schema_sha256"] != schema_hash(P["columns"]): raise ValueError("feature schema changed since the model was fitted")
        if P["math"]["detector_sha256"] != pv.DETECTOR_SHA256: raise ValueError("detector version differs from the model's")
        u = UnifiedScorer(P["mode"], P["columns"], P["n_boot"], P["seed"], P["thresholds"])
        if P["math"]["recal"]: u.math.recal = MathRecalibration(**P["math"]["recal"])
        u.chars.lo, u.chars.hi = np.array(P["characteristics"]["lo"]), np.array(P["characteristics"]["hi"])
        if P["mode"] != "math_only":
            pp = P["past"]; u.past.m = _pl_from(dict(columns=pp["columns"] + (["math_logit"] if pp["joint"] else []), lam=pp["lam"], beta=pp["beta"],
                                                       median=pp["median"], mean=pp["mean"], sd=pp["sd"], cw=pp["class_weight"]))
        u.boot = [(tuple(b["recal"]) if b["recal"] else None, _pl_from(b["past"])) for b in P["boot"]]
        u.fit_info = dict(P["training"]); u.model_hash = d["model_hash"]
        return u


def to_rows(results):
    """flat view (one dict per candidate) for tables; the full trace stays in the result objects"""
    return [dict(cand_key=r.cand_key, patient_key=r.patient_key, exam_id=r.exam_id, p=r.unified["p"], p_lo=r.unified["p_lo"], p_hi=r.unified["p_hi"],
                 category=r.unified["category"], math_score_v4=r.math["score_v4"], math_logit=r.math["logit"], increment=r.learned["increment"],
                 n_flags=len(r.quality_flags), model_hash=r.trace["model_hash"]) for r in results]
