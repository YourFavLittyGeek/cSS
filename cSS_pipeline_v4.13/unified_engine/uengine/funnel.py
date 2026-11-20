"""funnel.py - the detector's candidate funnel and the selection it imposes on any candidate-level model.

Stages (scripts/detect_css.py, manifest 'fates'):
  raw dark components -> not seeded (never objects) -> objects -> gate-dropped (G0-G4: work/ID_dropped.csv, few measurements)
  -> merged candidate objects with full measurements -> rule-excluded (E1-E29, review/ID_excluded.csv; fixed rules = MATH)
  -> E30-excluded (learned confidence model = PAST EXPERIENCE) -> shown to the reader (review/ID_candidates.csv)
  Lesions that never became an object ('not generated', labels/missed_lesions.csv) are OUTSIDE the reach of any candidate model.

What this module enforces for the learned component:
  - every object carries its fate and a measurement_complete flag; gate-dropped objects are measurement_complete = False;
  - E30-excluded objects are NOT silently dropped from the population: they are kept with selection='learned_model' so that a new
    model is not trained on a population filtered by the old model's opinion;
  - labels of excluded objects exist only where a reader audited them. Their inclusion probability must come from a DECLARED
    sampling design; there is no default. review_web.py's design (verified in the source): '--show-excluded' = census of all excluded
    objects; '--audit' = a seeded simple random sample of round(20 %) (>= 1) per (study, reviewer) drawn from the excluded objects
    whose reason does NOT start with 'infratentorial' (E1 objects have inclusion probability 0); the audit file does not record which
    of the two modes produced it, so the design cannot be recovered from the file and must be declared by the user."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .feature_schema import GATE_IDS

FATES = ("shown", "rule_excluded", "learned_excluded", "gate_dropped", "not_generated")


def fate_of(row_list, rule_version):
    s = str(rule_version or "")
    if row_list == "dropped": return "gate_dropped"
    if row_list == "missed": return "not_generated"
    if row_list == "candidates": return "shown"
    if s.startswith("E30"): return "learned_excluded"
    if s.startswith("E"): return "rule_excluded"
    raise ValueError(f"excluded row without an exclusion rule id ({rule_version!r})")


def build_population(candidates=None, excluded=None, dropped=None, missed=None, exam_id=None):
    """one table of every object of one examination with fate / selection / measurement_complete / rule_id"""
    parts = []
    for name, d in (("candidates", candidates), ("excluded", excluded), ("dropped", dropped), ("missed", missed)):
        if d is None or not len(d): continue
        d = d.copy(); d["_list"] = name
        d["fate"] = [fate_of(name, rv) for rv in (d["rule_version"] if "rule_version" in d.columns else [None] * len(d))]
        parts.append(d)
    if not parts: return pd.DataFrame(columns=["fate"])
    P = pd.concat(parts, ignore_index=True, sort=False)
    P["rule_id"] = [str(rv).split("@")[0] if f in ("rule_excluded", "learned_excluded") else "" for rv, f in
                    zip(P.get("rule_version", pd.Series([None] * len(P))), P.fate)]
    if "gate_id" in P.columns:
        bad = set(P.loc[P.fate == "gate_dropped", "gate_id"].dropna().astype(str)) - set(GATE_IDS) - {""}
        if bad: raise ValueError(f"unknown generation gate ids {bad}")
    P["selection"] = P.fate.map({"shown": "none", "rule_excluded": "fixed_rule", "learned_excluded": "learned_model",
                                 "gate_dropped": "generation_gate", "not_generated": "not_generated"})
    P["measurement_complete"] = P.fate.isin(["shown", "rule_excluded", "learned_excluded"])
    if exam_id is not None: P["exam_id"] = exam_id
    return P


def funnel_counts(P):
    return {f: int((P.fate == f).sum()) for f in FATES}


@dataclass(frozen=True)
class SamplingDesign:
    """how the reader labels of EXCLUDED objects of one (exam, reader) were obtained. kind: 'census' | 'srs' | 'unknown'.
    srs: n drawn without replacement from N_eligible eligible objects; ineligible_rules have inclusion probability 0."""
    kind: str
    N_eligible: int = 0
    n: int = 0
    ineligible_rules: tuple = ()
    source: str = ""

    def inclusion_probability(self, rule_id):
        if self.kind == "census": return 1.0
        if self.kind == "srs":
            if rule_id in self.ineligible_rules: return 0.0
            if self.N_eligible <= 0 or self.n <= 0: raise ValueError("srs design needs N_eligible and n")
            return min(1.0, self.n / self.N_eligible)
        return None                                                  # unknown: no weight can be justified


def review_web_audit_design(excluded_reasons, mode):
    """the design review_web.py implements (verified in source_snapshot/scripts/review_web.py audit_ids):
    mode 'show_excluded' -> census; mode 'audit' -> srs over reasons not starting with 'infratentorial', n = max(1, round(0.2 N))."""
    if mode == "show_excluded": return SamplingDesign("census", source="review_web --show-excluded")
    if mode == "audit":
        N = sum(not str(r).lower().startswith("infratentorial") for r in excluded_reasons)
        return SamplingDesign("srs", N, max(1, int(round(0.2 * N))) if N else 0, ("E1",), "review_web --audit (seeded per study + reviewer)")
    return SamplingDesign("unknown", source=f"mode {mode!r} not declared")


def label_weights(P, designs):
    """inverse-probability weights for labelled objects. designs: dict exam_id -> SamplingDesign for the excluded lists.
    shown objects: weight 1 (every shown object is read - REQUIRES a complete read; caller asserts it).
    rule/learned-excluded: 1 / p when the design gives p > 0; NaN when the design is unknown or p == 0 (not usable for inference).
    gate-dropped / not generated: NaN (outside the candidate model)."""
    w = np.full(len(P), np.nan)
    for i, (f, rid, ex) in enumerate(zip(P.fate, P.rule_id, P.get("exam_id", pd.Series([None] * len(P))))):
        if f == "shown": w[i] = 1.0
        elif f in ("rule_excluded", "learned_excluded"):
            d = designs.get(ex)
            p = None if d is None else d.inclusion_probability(rid)
            w[i] = (1.0 / p) if p else np.nan
    return w


def selection_report(P, y_col="y"):
    """how a training set drawn from P would be selected: counts per fate x labelled, and the share of labelled objects per fate"""
    lab = P[y_col].notna() if y_col in P.columns else pd.Series(False, index=P.index)
    rep = {}
    for f in FATES:
        m = P.fate == f
        rep[f] = dict(n=int(m.sum()), labelled=int((m & lab).sum()))
    rep["warning"] = []
    if rep["learned_excluded"]["n"] and not rep["learned_excluded"]["labelled"]:
        rep["warning"].append("E30-excluded objects carry no labels: a model trained on shown objects inherits the confidence model's selection")
    if rep["rule_excluded"]["n"] and not rep["rule_excluded"]["labelled"]:
        rep["warning"].append("rule-excluded objects carry no labels: the model only learns inside the rules' acceptance region")
    if rep["gate_dropped"]["labelled"]:
        rep["warning"].append("gate-dropped objects are labelled but have incomplete measurements: keep them out of the feature model")
    return rep
