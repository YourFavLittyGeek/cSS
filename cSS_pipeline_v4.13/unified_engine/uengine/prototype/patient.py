"""patient.py - PATIENT-level layer, a separate type. It aggregates candidate results of one patient (all examinations); nothing here
is ever fed back into candidate scoring, and the candidate model never sees a patient-level value. The MATH 0-4 patient score
(score_css.py, recorded) is carried separately and is never mixed with the candidate probabilities."""
from dataclasses import dataclass, field
import numpy as np

CATEGORIES = ("likely_cSS", "uncertain", "unlikely_cSS", "not_scorable")


@dataclass(frozen=True)
class PatientResult:
    patient_key: str
    exams: tuple
    n_candidates: int
    counts: dict
    max_p: float                     # highest unified probability among scorable candidates (None if none)
    candidates_for_review: tuple     # likely + uncertain candidate keys, highest p first
    math_patient_score: dict = field(default=None)   # recorded 0-4 (L, R, total) when supplied, untouched
    note: str = "aggregation of candidate reading aids; NOT a patient diagnosis and NOT the 0-4 score"


def patient_summary(results, math_scores=None):
    by = {}
    for r in results: by.setdefault(r.patient_key, []).append(r)
    out = []
    for pk, rs in sorted(by.items()):
        cnt = {c: sum(r.unified["category"] == c for r in rs) for c in CATEGORIES}
        ps = [r.unified["p"] for r in rs if r.unified["p"] is not None and np.isfinite(r.unified["p"])]
        rev = sorted((r for r in rs if r.unified["category"] in ("likely_cSS", "uncertain")), key=lambda r: -(r.unified["p"] if r.unified["p"] is not None and np.isfinite(r.unified["p"]) else -1))
        out.append(PatientResult(pk, tuple(sorted({r.exam_id for r in rs})), len(rs), cnt, max(ps) if ps else None,
                                 tuple(r.cand_key for r in rev), (math_scores or {}).get(pk)))
    return out
