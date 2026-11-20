"""unified_fusion.py - the FUTURE fusion interface. Unified Score = f(MATH, CHARACTERISTICS, PAST EXPERIENCE). Gate-locked.

What exists now:
  ComponentBundle   per candidate: MathEvidence, CharacteristicsEvidence, LearnedEvidence, QualityIndicators - kept SEPARATE
  fuse()            returns the components side by side, their disagreement and the quality flags; unified_score is None and
                    status says why, unless a GateDAuthorization object is passed AND its checklist is complete. No trained fusion
                    model exists in this workspace and none may be trained here (Gate C / D).
  incremental_value()  the analysis Gate D needs, runnable on SYNTHETIC data: math-only (recalibrated score_v4) vs math + learned
                    increment (offset model) on identical patient folds; within-patient AUC, log loss, calibration, patient bootstrap.
Design rules (OVERLAP_AND_DOUBLE_COUNTING.md):
  1. The math component enters ONCE, as a recalibrated logit (2 learned parameters, monotone: math order unchanged).
  2. The learned component is fitted with that logit as an OFFSET: it estimates only what characteristics add beyond math. The
     same characteristic therefore cannot be counted once inside score_v4 and again as an independent learned term.
  3. Characteristics are not a third additive score: they are the measured inputs of 1 and 2 (shown for inspection).
  4. Quality indicators never add evidence; they gate (withhold / flag) a unified output.
  5. Disagreement between components is reported, never averaged away."""
from dataclasses import dataclass, field
import numpy as np
from .math_component import MathEvidence
from .characteristics_component import CharacteristicsEvidence

GATE_D_CHECKLIST = ("each component shows useful information on independent patients",
                    "improvement over the existing mathematical score (within-patient discrimination and log loss) with CI excluding 0",
                    "calibration slope and intercept acceptable on independent patients",
                    "independent patient-level evaluation (protected test set, frozen model)",
                    "documented scientific rationale signed by the responsible investigator")


class FusionNotAuthorized(RuntimeError): pass


@dataclass
class LearnedEvidence:
    model: str                          # e.g. 'increment_lr_v0' or 'legacy_confidence_v5.10'
    logit_increment: float = None       # learned log-odds beyond the math offset (None if no frozen model)
    contributions: dict = field(default_factory=dict)
    legacy_confidence_pct: float = None # v5.10 confidence (shown for comparison; never re-used as an input)
    status: str = "no frozen model"


@dataclass
class QualityIndicators:
    registration: str = "unverified"    # ok / marginal / unreliable / swi_only / unverified
    missing_t1_anatomy: int = 0
    missing_flair: int = 0
    measurement_complete: bool = True
    characteristics_completeness: float = 1.0
    flags: list = field(default_factory=list)


@dataclass
class ComponentBundle:
    candidate: str
    math: MathEvidence
    characteristics: CharacteristicsEvidence
    learned: LearnedEvidence
    quality: QualityIndicators


@dataclass
class GateDAuthorization:
    checklist: dict                     # item -> evidence reference (all GATE_D_CHECKLIST items required)
    fusion_model_hash: str
    authorized_by: str
    date: str

    def complete(self):
        return all(str(self.checklist.get(k, "")).strip() for k in GATE_D_CHECKLIST) and self.fusion_model_hash and self.authorized_by and self.date


@dataclass
class FusionResult:
    candidate: str
    unified_score: float
    status: str
    components: dict
    disagreement: list
    quality_flags: list


def quality_flags(q: QualityIndicators):
    f = list(q.flags)
    if q.registration in ("unreliable", "unverified"): f.append(f"registration {q.registration}: surface / location measures not trustworthy")
    if not q.measurement_complete: f.append("measurements incomplete (gate-dropped object): outside the candidate model")
    if q.characteristics_completeness < 0.8: f.append(f"only {100 * q.characteristics_completeness:.0f} % of the measures usable")
    return f


def disagreement(b: ComponentBundle, rank_math=None, rank_learned=None):
    """flags when the components point in different directions. rank_* = within-patient percentile ranks (0-1) if available."""
    d = []
    if b.math.rule_fate and b.learned.logit_increment is not None and b.learned.logit_increment > 1.0:
        d.append(f"excluded by MATH rule {b.math.rule_fate} but the learned increment is strongly positive")
    if rank_math is not None and rank_learned is not None and abs(rank_math - rank_learned) >= 0.5:
        d.append(f"MATH ranks it at {100 * rank_math:.0f} %, learned at {100 * rank_learned:.0f} % within the scan")
    if b.learned.legacy_confidence_pct is not None and b.math.review_tier == 1 and b.learned.legacy_confidence_pct < 10:
        d.append("MATH tier 1 (no mimic evidence) but the legacy confidence model is below 10 %")
    return d


def fuse(b: ComponentBundle, authorization: GateDAuthorization = None, fusion_fn=None, **ranks):
    comps = dict(math=dict(score_v4=b.math.score_v4, evidence_difference=b.math.evidence_difference, rule_fate=b.math.rule_fate,
                           review_tier=b.math.review_tier, review_priority_rank=b.math.review_priority_rank),
                 characteristics=dict(completeness=b.characteristics.completeness,
                                      not_ok={k: v for k, v in b.characteristics.status.items() if v != "ok"}),
                 learned=dict(model=b.learned.model, logit_increment=b.learned.logit_increment, status=b.learned.status,
                              legacy_confidence_pct=b.learned.legacy_confidence_pct))
    qf = quality_flags(b.quality); dis = disagreement(b, ranks.get("rank_math"), ranks.get("rank_learned"))
    if authorization is None or not authorization.complete() or fusion_fn is None:
        return FusionResult(b.candidate, None, "NOT AUTHORIZED: Gate D not passed - components reported separately, no unified score", comps, dis, qf)
    if qf: return FusionResult(b.candidate, None, "WITHHELD: data-quality flags", comps, dis, qf)
    return FusionResult(b.candidate, float(fusion_fn(b)), "authorized", comps, dis, qf)


# ---------------- incremental value (Gate D evidence) - SYNTHETIC use only in this workspace
def incremental_value(df, y, patients, assignment, columns, matrix_fn, repeat=0, B=300, seed=0):
    """identical folds: M = recalibrated math only; M+L = math offset + learned increment on `columns`; also NAIVE = independent
    learned model + math logit added (double counting). -> dict of per-model metrics and the paired difference (M+L) - M."""
    from .ml_component import PenalizedLogistic, MathRecalibration, sigmoid, logloss
    from .model_evaluation import auc_decomposition, cluster_bootstrap
    from .calibration import calibration_slope_intercept
    from . import patient_split as ps
    y = np.asarray(y, float); pid = np.asarray(patients).astype(str); X = matrix_fn(df); s4 = df["score_v4"].to_numpy(float)
    out = {k: np.full(len(y), np.nan) for k in ("math", "math_plus_learned", "naive_sum")}
    for tr, te in ps.fold_indices(assignment, pid, repeat):
        if len(np.unique(y[tr])) < 2: continue
        rc = MathRecalibration().fit(s4[tr], y[tr]); off_tr, off_te = rc.logit(s4[tr]), rc.logit(s4[te])
        out["math"][te] = sigmoid(off_te)
        inc = PenalizedLogistic(columns).fit_nested(X[tr], y[tr], pid[tr], offset=off_tr, seed=seed)
        out["math_plus_learned"][te] = inc.predict(X[te], off_te)
        ind = PenalizedLogistic(columns).fit_nested(X[tr], y[tr], pid[tr], seed=seed)
        out["naive_sum"][te] = sigmoid(ind.logit(X[te]) + off_te)          # what "add the scores" would do
    ok = np.isfinite(out["math"]) & np.isfinite(out["math_plus_learned"])
    res = {}
    for k, p in out.items():
        d = auc_decomposition(y[ok], p[ok], pid[ok]); c = calibration_slope_intercept(y[ok], p[ok])
        res[k] = dict(within_patient_auc=d["within"], pooled_auc=d["pooled"], logloss=logloss(y[ok], p[ok]), cal_slope=c["slope"], cal_citl=c["citl"])
    def d_within(yy, ss, pp):
        return auc_decomposition(yy, ss[:, 0], pp)["within"] - auc_decomposition(yy, ss[:, 1], pp)["within"]
    S = np.c_[out["math_plus_learned"][ok], out["math"][ok]]
    res["delta_within_auc"] = res["math_plus_learned"]["within_patient_auc"] - res["math"]["within_patient_auc"]
    res["delta_within_auc_ci"] = cluster_bootstrap(d_within, y[ok], S, pid[ok], B=B, seed=seed)
    res["delta_logloss"] = res["math_plus_learned"]["logloss"] - res["math"]["logloss"]
    res["synthetic_only"] = True
    return res
