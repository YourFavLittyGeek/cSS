"""math_component.py - the EXISTING deterministic system ("MATH"), preserved exactly.

Engine: the production detector's own code text, extracted VERBATIM from the pinned snapshot of scripts/detect_css.py
(sha256 in provenance.DETECTOR_SHA256) and executed with explicit inputs:
  score_v4 block    'on_surf = ...' .. the multiplicative flag loop     -> score_v4
  evidence block    'fin = lambda ...' .. 'vein_ev = ...'                 -> css_evidence, vein_evidence
  review_tier       the 4-line inline rule                                -> review_tier (1 / 2), tier_reason
  exclusion_v4()    the whole function (rules E1-E29 in file order)       -> rule id or ''
  review_priority() css_tiers.py, imported verbatim                       -> tier 1-5
Nothing here changes a formula or a threshold. A separate, independently written replica (replica_*) exists ONLY so the tests
can show that the formulas are understood; the engine never uses it.

NOT part of MATH (moved to PAST EXPERIENCE): E30 (low confidence; learned model css_confidence) and the side guard that undoes E30.
NOT recomputable from the candidate table (documented limits):
  - E12 needs the internal per-object flag _band (not written to the CSV) -> recorded rule_version is authoritative;
  - E3 / E8 need FULL_BOTTOM (a per-scan coverage fact) and E1 / E2 / E7 need T1_ANAT -> passed in as scan context;
  - the patient-level 0-4 score (score_css.py) needs the label images (Destrieux adjacency) -> taken from ID_score.json as recorded.
CSV values are rounded by the detector (e.g. darkness_z to 0.1), so a recomputation from a CSV row agrees with the recorded
score_v4 only within rounding; consistency() reports the difference instead of hiding it."""
import math, os
from dataclasses import dataclass, field, asdict
import numpy as np
from . import provenance as pv

# ---------------- verbatim code blocks (extracted once, hashed; tests pin the hashes)
SCORE_V4_SRC = pv.extract_lines("on_surf = float(np.exp(-((pdist + 0.5) / 1.5) ** 2))", 'if USE_MIMIC and mim["_flair_class"]')
EVIDENCE_SRC = pv.extract_lines("fin = lambda v: v if np.isfinite(v) else None", "vein_ev = float(np.mean", include_end=True)
TIER_SRC = pv.extract_lines('why = [n for n, f in (("artifact zone", r["artifact_zone"])', 'r["review_tier"] = 2 if why else 1', include_end=True)
EXCLUSION_SRC = pv.function_source("exclusion_v4")
_SCORE_CODE = compile(SCORE_V4_SRC, "detect_css.py:score_v4", "exec")
_EVID_CODE = compile(EVIDENCE_SRC, "detect_css.py:evidence", "exec")
_TIER_CODE = compile(TIER_SRC, "detect_css.py:review_tier", "exec")
VES_EXCL_WM_MM = 4.0      # detector constant used by the evidence block (checked against the source in the tests)

SWITCHES = ("KEEP_ALL", "T1_ANAT", "FULL_BOTTOM", "V53", "ZONE2", "STRUCT", "E22_PIECES", "USE_MIMIC")


def _production_constants():
    """detector module constants evaluated with NO CSS_* environment variable (= production defaults)"""
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("CSS_")}
    try: return pv.module_constants()
    finally: os.environ.update(saved)


CONSTANTS = _production_constants()


@dataclass(frozen=True)
class ScanContext:
    """per-scan facts and detector switches the rules depend on. Defaults = the configuration of the user's last lists
    (CSS_V53=1 CSS_ZONE2=1, T1 anatomy, full skull-base coverage). E30 / CSS_CONF is deliberately absent (not MATH)."""
    T1_ANAT: bool = True
    FULL_BOTTOM: bool = True
    V53: bool = True
    ZONE2: bool = True
    STRUCT: bool = False
    E22_PIECES: bool = True
    USE_MIMIC: bool = False
    KEEP_ALL: bool = False


def _exclusion_fn(ctx: ScanContext):
    ns = dict(CONSTANTS); ns["np"] = np; ns.update(asdict(ctx))
    exec(compile(EXCLUSION_SRC, "detect_css.py:exclusion_v4", "exec"), ns)
    return ns["exclusion_v4"]


def _f(r, k):
    v = r.get(k, np.nan)
    try: return float(v)
    except (TypeError, ValueError): return np.nan


def score_v4(r, use_mimic=False):
    """verbatim detector score_v4 from a row's inputs (darkness_z, pial_dist_mm, tube_ratio, surface_alignment, tram_frac,
    artifact_zone, midline_zone, long_structure, infratentorial). The CSS_USE_MIMIC x0.5 penalty is applied as in the detector
    when use_mimic and the FLAIR mimic class is set (flair_class argument via r['_flair_class'])."""
    ns = dict(np=np, depth=_f(r, "darkness_z"), pdist=_f(r, "pial_dist_mm"), tub=_f(r, "tube_ratio"), aln=_f(r, "surface_alignment"),
              tram=_f(r, "tram_frac"), artz=bool(_f(r, "artifact_zone") >= 1), midz=bool(_f(r, "midline_zone") >= 1),
              longs=bool(_f(r, "long_structure") >= 1), infra=bool(_f(r, "infratentorial") >= 1))
    exec(_SCORE_CODE, ns)
    s4 = ns["s4"]
    if use_mimic and str(r.get("_flair_class", "none")) != "none": s4 *= 0.5
    return float(s4)


def evidence(r):
    """verbatim css_evidence / vein_evidence (rule-based 0-1 summaries; NOT probabilities)"""
    ns = dict(np=np, pdist=_f(r, "pial_dist_mm"), tub=_f(r, "tube_ratio"), aln=_f(r, "surface_alignment"), tram=_f(r, "tram_frac"),
              bankf=_f(r, "bank_frac"), axn=_f(r, "axis_normal"), ves_wm=_f(r, "vessel_wm_mm"), VES_EXCL_WM_MM=VES_EXCL_WM_MM)
    ns["on_surf"] = float(np.exp(-((ns["pdist"] + 0.5) / 1.5) ** 2))   # defined in the score block; same expression
    exec(_EVID_CODE, ns)
    return float(ns["css_ev"]), float(ns["vein_ev"])


def review_tier(r):
    """verbatim v4.18 review tier (1 / 2) and reason from a row (needs artifact_zone, vein_like, cmb_like, css/vein_evidence)"""
    row = {k: r.get(k) for k in ("artifact_zone", "vein_like", "cmb_like", "vein_evidence", "css_evidence")}
    ns = dict(r=row); exec(_TIER_CODE, ns)
    return int(row["review_tier"]), row["tier_reason"]


def review_priority(r, qc_status="ok"):
    """verbatim css_tiers.review_priority (reading order 1-5)"""
    return pv.load_legacy("css_tiers").review_priority(r, qc_status)


class ExclusionEngine:
    """verbatim exclusion_v4 bound to a ScanContext. Rows must carry the columns the rules read; '_band' (E12) defaults to False
    because the detector does not write it (so E12 is never reproduced from a CSV row - documented)."""
    def __init__(self, ctx: ScanContext = ScanContext()):
        self.ctx = ctx; self._fn = _exclusion_fn(ctx)

    def fate(self, r):
        row = dict(r); row.setdefault("_band", False)
        for k in ("tram_frac", "tube_ratio", "edge_contrast", "struct_ctx_frac", "struct_surf_cos"):
            row[k] = _f(row, k)
        rv, why = self._fn(row)
        return rv, why


@dataclass
class MathEvidence:
    """the MATH component's output for one candidate (recorded values are authoritative; recomputed values are a check)"""
    score_v4: float
    css_evidence: float
    vein_evidence: float
    evidence_difference: float          # css - vein: the comparison the detector itself uses ("vein evidence > cSS evidence")
    rule_fate: str                      # '' = kept by E1-E29; else the rule id (E30 is reported by the learned component)
    review_tier: int
    review_priority_rank: int
    consistency: dict = field(default_factory=dict)


def rule_id(rule_version):
    s = str(rule_version or "")
    return s.split("@")[0] if s.startswith("E") else ""


def from_row(r, qc_status="ok"):
    """MathEvidence from a detector row. Recorded score_v4 / evidence / tiers are used as they are; the verbatim engine recomputes
    them from the row's inputs and the difference is stored in .consistency."""
    s4r = score_v4(r); ce, ve = evidence(r)
    rec = lambda k, d: _f(r, k) if np.isfinite(_f(r, k)) else d
    rid = rule_id(r.get("rule_version"))
    tier = r.get("review_tier"); prio = r.get("review_priority_rank")
    if tier is None or (isinstance(tier, float) and not np.isfinite(tier)): tier = review_tier({**r, "css_evidence": ce, "vein_evidence": ve})[0]
    if prio is None or (isinstance(prio, float) and not np.isfinite(prio)): prio = review_priority(r, qc_status)[0]
    s4, c_, v_ = rec("score_v4", s4r), rec("css_evidence", ce), rec("vein_evidence", ve)
    return MathEvidence(score_v4=s4, css_evidence=c_, vein_evidence=v_, evidence_difference=c_ - v_,
                        rule_fate="E30-is-learned" if rid == "E30" else rid, review_tier=int(tier), review_priority_rank=int(prio),
                        consistency=dict(score_v4_recomputed=s4r, score_v4_abs_diff=abs(s4 - s4r),
                                         css_evidence_abs_diff=abs(c_ - ce), vein_evidence_abs_diff=abs(v_ - ve)))


def consistency_ok(me: MathEvidence, tol_score=0.06, tol_ev=0.011):
    """recomputation from ROUNDED CSV inputs agrees within rounding (score_v4 relative tolerance, evidence absolute)"""
    c = me.consistency
    return (c["score_v4_abs_diff"] <= tol_score * max(1.0, abs(me.score_v4)) and c["css_evidence_abs_diff"] <= tol_ev
            and c["vein_evidence_abs_diff"] <= tol_ev)


def patient_score(score_json):
    """patient-level 0-4 multifocality as RECORDED by score_css.py (ID_score.json). Not recomputed here (needs label images).
    Returns dict(L, R, total) or None. Accepts the key spellings used by score_css.py and the reviewer."""
    if not score_json: return None
    g = lambda *ks: next((score_json[k] for k in ks if k in score_json and score_json[k] is not None), None)
    L, R, T = g("L", "L_score", "left"), g("R", "R_score", "right"), g("multifocality_0_4", "total", "css_score", "score")
    if L is None and R is None and T is None: return None
    return dict(L=L, R=R, total=T if T is not None else (None if L is None or R is None else L + R))


# ---------------- independent replica (cross-check only; written from the definitions, not copied)
def replica_score_v4(r):
    depth, pdist, tub, aln, tram = (_f(r, k) for k in ("darkness_z", "pial_dist_mm", "tube_ratio", "surface_alignment", "tram_frac"))
    on_surf = math.exp(-((pdist + 0.5) / 1.5) ** 2)
    sheet = 1.0 - (tub if math.isfinite(tub) else 0.5)
    s = math.sqrt(max(depth, 0.0)) * (0.25 + on_surf) * (0.25 + sheet) * (0.5 + (aln if math.isfinite(aln) else 0.5)) * (1.0 + (tram if math.isfinite(tram) else 0.0))
    for k, f in (("artifact_zone", 0.5), ("midline_zone", 0.7), ("long_structure", 0.5), ("infratentorial", 0.3)):
        if _f(r, k) >= 1: s *= f
    return s


def replica_evidence(r):
    pdist, tub, aln, tram, bank, axn, wm = (_f(r, k) for k in ("pial_dist_mm", "tube_ratio", "surface_alignment", "tram_frac", "bank_frac",
                                                                  "axis_normal", "vessel_wm_mm"))
    on_surf = math.exp(-((pdist + 0.5) / 1.5) ** 2)
    ce = [on_surf, 1 - tub if math.isfinite(tub) else None, aln if math.isfinite(aln) else None, tram if math.isfinite(tram) else None, bank]
    ve = [tub if math.isfinite(tub) else None, 1 / (1 + math.exp(-(pdist - 0.3) / 0.5)), 1 - aln if math.isfinite(aln) else None, axn, min(wm / 4.0, 1.0)]
    m = lambda xs: float(np.mean([x for x in xs if x is not None]))
    return m(ce), m(ve)
