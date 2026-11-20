"""components.py - the three separately identifiable components. Each has fit(), an output method and params() / hash() so it can be
replaced without touching the others (fusion.UnifiedScorer only uses these methods).

MathComponent              MATH. score_v4 is taken as RECORDED when present (authoritative) and otherwise computed by the VERBATIM
                           detector block; a recorded value that disagrees with the verbatim recomputation beyond rounding is flagged
                           'inconsistent'. Rule fate and tiers are passed through as recorded. The only learned part is the 2-parameter
                           monotone recalibration logit = a + b log(score_v4 + 0.05) (needed to put MATH on the log-odds scale).
CharacteristicsComponent   CHARACTERISTICS. The 10 declared input columns with per-value status; training reference ranges; values beyond
                           the training range are CLIPPED for the learned part and flagged 'extrapolation' (never silently extrapolated).
IncrementComponent         PAST EXPERIENCE. Penalised LR fitted with the MATH logit as an OFFSET: its output is the log-odds evidence
                           BEYOND MATH, with per-feature contributions. Also usable without offset (learned-only) or with the math logit
                           as one more free column (joint) for ablations.
NullPastExperience         increment 0 (MATH only)."""
import hashlib, json
import numpy as np
from .. import feature_schema as fs, math_component as mc, provenance as pv
from ..characteristics_component import design_row
from ..ml_component import PenalizedLogistic, MathRecalibration

MEASURED_INPUTS = [c for c in fs.INITIAL_COLUMNS if c not in fs.INITIAL_INDICATORS]


def _hash(d): return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def _f(v):
    try: x = float(v)
    except (TypeError, ValueError): return np.nan
    return x if np.isfinite(x) else np.nan


class MathComponent:
    name = "math_v4_verbatim"
    SCORE_INPUTS = ("darkness_z", "pial_dist_mm")          # required for a verbatim recomputation (others have NaN branches)

    def __init__(self, tol=0.06):
        self.tol = tol; self.recal = None

    def outputs(self, row):
        rec = _f(row.get("score_v4")); can = all(np.isfinite(_f(row.get(k))) for k in self.SCORE_INPUTS)
        comp = mc.score_v4(row) if can else np.nan
        status, source = "ok", "recorded"
        if np.isfinite(rec):
            s = rec
            if np.isfinite(comp) and abs(rec - comp) > self.tol * max(1.0, abs(rec)): status = "inconsistent"
        elif np.isfinite(comp): s, source = comp, "computed_verbatim"
        else: s, source, status = np.nan, "none", "not_scorable"
        if np.isfinite(s) and s < 0: s, status = np.nan, "not_scorable"     # score_v4 is a product of non-negative terms
        tier = _f(row.get("review_tier")); prio = _f(row.get("review_priority_rank"))
        out = dict(score_v4=s, source=source, recomputed=comp, status=status, rule_fate=mc.rule_id(row.get("rule_version")),
                   css_evidence=_f(row.get("css_evidence")), vein_evidence=_f(row.get("vein_evidence")),
                   review_tier=None if not np.isfinite(tier) else int(tier), review_priority_rank=None if not np.isfinite(prio) else int(prio))
        out["logit"] = float(self.recal.logit(s)) if (self.recal is not None and np.isfinite(s)) else np.nan
        return out

    def fit(self, scores, y, w=None):
        self.recal = MathRecalibration().fit(np.asarray(scores, float), np.asarray(y, float), w); return self

    def refit(self, scores, y):
        r = MathRecalibration().fit(np.asarray(scores, float), np.asarray(y, float)); return (r.a, r.b)

    def params(self): return dict(name=self.name, detector_sha256=pv.DETECTOR_SHA256, tol=self.tol,
                                  recal=None if self.recal is None else dict(a=self.recal.a, b=self.recal.b, eps=self.recal.eps))


class CharacteristicsComponent:
    name = "characteristics_initial10"

    def __init__(self, columns=fs.INITIAL_COLUMNS, clip_quantiles=(0.005, 0.995)):
        self.columns = list(columns); self.q = clip_quantiles; self.lo = self.hi = None

    def outputs(self, row, input_status=None):
        vals, st = design_row(row, self.columns)
        for c in self.columns:                                            # corrupt / out-of-range from input validation win
            src = fs.TRANSFORMS[c][0] if c in fs.TRANSFORMS else fs.INITIAL_INDICATORS.get(c, c)
            s = (input_status or {}).get(src)
            if s == "corrupt": vals[c], st[c] = np.nan, "corrupt"
        x = np.array([vals[c] for c in self.columns], float); flags = []
        if self.lo is not None:
            ok = np.isfinite(x); xc = np.clip(x, self.lo, self.hi)
            ext = ok & ((x < self.lo) | (x > self.hi))
            for j in np.where(ext)[0]: st[self.columns[j]] = "extrapolation_clipped"; flags.append(self.columns[j])
            x = np.where(ok, xc, x)
        carried = set(fs.INITIAL_INDICATORS.values())            # structural missingness carried by an indicator is information, not loss
        n_bad = sum(st[c] not in ("ok", "extrapolation_clipped") and not (c in carried and st[c] == "missing_structural")
                    for c in MEASURED_INPUTS if c in st)
        return dict(values=dict(zip(self.columns, x)), status=st, n_missing_or_invalid=n_bad, extrapolated=flags), x

    def fit(self, X):
        X = np.asarray(X, float)
        self.lo = np.array([np.nanquantile(c, self.q[0]) if np.isfinite(c).any() else -np.inf for c in X.T])
        self.hi = np.array([np.nanquantile(c, self.q[1]) if np.isfinite(c).any() else np.inf for c in X.T])
        return self

    def params(self): return dict(name=self.name, columns=self.columns, clip_quantiles=self.q,
                                  lo=None if self.lo is None else self.lo.tolist(), hi=None if self.hi is None else self.hi.tolist())


class IncrementComponent:
    """offset=True: learned evidence beyond MATH. offset=False: learned-only. joint=True: math logit as a free column (no offset)."""
    def __init__(self, columns=fs.INITIAL_COLUMNS, offset=True, joint=False, class_weight="none"):
        self.columns, self.offset, self.joint, self.cw = list(columns), offset, joint, class_weight
        self.name = "increment_lr_offset" if offset else ("joint_lr" if joint else "learned_only_lr")
        self.m = None

    def _X(self, X, math_logit):
        return np.c_[X, math_logit] if self.joint else X

    def fit(self, X, y, patients, math_logit=None, seed=0):
        cols = self.columns + (["math_logit"] if self.joint else [])
        self.m = PenalizedLogistic(cols, class_weight=self.cw).fit_nested(self._X(X, math_logit), y, patients,
                                                                           offset=math_logit if self.offset else None, seed=seed)
        return self

    def refit(self, X, y, math_logit, lam):
        m = PenalizedLogistic(self.m.columns, class_weight=self.cw).fit(self._X(X, math_logit), y, lam, offset=math_logit if self.offset else None)
        return m

    def increment(self, X, math_logit=None, model=None):
        """learned log-odds (intercept + contributions); excludes the offset"""
        m = model or self.m; Xd = self._X(X, math_logit); return m.logit(Xd), m.contributions(Xd), float(m.beta[0])

    def params(self):
        m = self.m
        return dict(name=self.name, columns=self.columns, offset=self.offset, joint=self.joint, class_weight=self.cw,
                    lam=None if m is None else m.lam, beta=None if m is None else m.beta.tolist(),
                    median=None if m is None else m.pre.median.tolist(), mean=None if m is None else m.pre.mean.tolist(),
                    sd=None if m is None else m.pre.sd.tolist(), converged=None if m is None else bool(m.converged))


class NullPastExperience:
    name = "null_past_experience"
    offset, joint, columns = True, False, []

    def fit(self, *a, **k): return self

    def refit(self, *a, **k): return None

    def increment(self, X, math_logit=None, model=None):
        n = len(X); return np.zeros(n), np.zeros((n, 0)), 0.0

    def params(self): return dict(name=self.name)


__all__ = ["MathComponent", "CharacteristicsComponent", "IncrementComponent", "NullPastExperience", "MEASURED_INPUTS"]
