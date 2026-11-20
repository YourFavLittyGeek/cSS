"""experiment.py - end-to-end SYNTHETIC experiment: funnel -> population -> leakage checks -> identical patient folds ->
new model + comparators -> candidate- and patient-level summaries -> incremental value of learned evidence over MATH.
Refuses anything but synthetic tables (every row must carry synthetic=True and SYN identifiers)."""
import numpy as np
from . import synthetic as sy, funnel as fn, patient_split as ps, data_validation as dv, model_evaluation as ev
from . import characteristics_component as cc, feature_schema as fs, ml_component as ml, unified_fusion as uf


class NotSynthetic(RuntimeError): pass


def _assert_synthetic(df):
    if "synthetic" not in df.columns or not df.synthetic.all() or not df.patient_key.astype(str).str.startswith("SYN").all():
        raise NotSynthetic("this workspace runs experiments on SYNTHETIC tables only")


class NewLR:
    """PAST EXPERIENCE: the prespecified characteristics model (INITIAL_COLUMNS), nested penalty, training-fold preprocessing"""
    name = "new_lr_initial10"

    def fit(self, d, y, p):
        X, _ = cc.design_matrix(d); dv.assert_predictors_allowed(fs.INITIAL_COLUMNS)
        self.m = ml.PenalizedLogistic(fs.INITIAL_COLUMNS).fit_nested(X, y, p, seed=0); return self

    def score(self, d): return self.m.predict(cc.design_matrix(d)[0])


def univariate(col, src=None):
    class U:
        name = f"char_{col}"

        def fit(self, d, y, p):
            x = _x(d); ok = np.isfinite(x)
            self.sign = 1.0 if np.nanmean(x[ok & (y == 1)]) >= np.nanmean(x[ok & (y == 0)]) else -1.0   # direction from training only
            self.fill = float(np.nanmedian(x[ok])); return self

        def score(self, d):
            x = _x(d); return self.sign * np.where(np.isfinite(x), x, self.fill)

    def _x(d):
        if col in fs.TRANSFORMS: s, f = fs.TRANSFORMS[col]; return f(d[s].to_numpy(float))
        return d[col].to_numpy(float)
    return U


def population(O, which="shown_and_audited"):
    """candidate-model population: measurement-complete, labelled objects. 'shown_only' reproduces the legacy selection."""
    m = O.measurement_complete & O.y.notna()
    if which == "shown_only": m &= O.fate == "shown"
    return O[m].reset_index(drop=True)


def run(n_patients=40, seed=0, signal=1.0, n_splits=5, n_repeats=2, B=200, which="shown_and_audited", legacy=True, **cohort_kw):
    O, E, P = sy.make_cohort(n_patients, seed=seed, signal=signal, **cohort_kw); _assert_synthetic(O)
    out = dict(synthetic=True, seed=seed, signal=signal, n_patients=n_patients, population=which)
    out["funnel"] = fn.funnel_counts(O); out["selection"] = fn.selection_report(O)
    D = population(O, which); y = D.y.to_numpy(float)
    km = ps.PatientKeyMap.from_table(E.to_dict("records")); pid = km.patients(D.exam_id)
    out["n_candidates"], out["n_cSS"], out["n_model_patients"] = len(D), int(y.sum()), len(set(pid))
    out["repeat_exam_patients"] = len(km.repeat_exams())
    # leakage / validation checks (raise on a forbidden predictor; findings recorded)
    dv.assert_predictors_allowed(fs.INITIAL_COLUMNS)
    X, counts = cc.design_matrix(D)
    out["checks"] = dict(near_perfect=dv.near_perfect_separation(X, y, fs.INITIAL_COLUMNS), duplicates=dv.duplicate_objects(D),
                         range_violations=dv.schema_ranges(D), status_counts=counts)
    lab = dict(zip(P.patient_key, P.positive))
    A = ps.grouped_folds(sorted(set(pid)), n_splits, n_repeats, seed, {q: lab[q] for q in set(pid)}, keymap_verified=km.verified, keymap_note=km.note)
    out["assignment_digest"] = A.digest(); out["assignment_notes"] = A.notes
    scorers = [ev.Scorer(NewLR.name, NewLR),
               ev.Scorer("math_score_v4", lambda d: d.score_v4.to_numpy(float), fitted=False, is_probability=False),
               ev.Scorer("math_evidence_difference", lambda d: (d.css_evidence - d.vein_evidence).to_numpy(float), fitted=False, is_probability=False)]
    scorers += [ev.Scorer(f"char_{c}", univariate(c), is_probability=False) for c in fs.INITIAL_FEATURES]
    if legacy:
        scorers += [ev.Scorer(ml.LegacyConfidence.name, ml.LegacyConfidence), ev.Scorer(ml.LegacyRanker.name, ml.LegacyRanker),
                    ev.Scorer(ml.LegacyUnified.name, ml.LegacyUnified)]
    R = ev.cross_validate(D, y, pid, A, scorers)
    out["candidate_level"] = {s.name: ev.summarise(R[s.name], y, pid, s.is_probability, B=B, seed=seed) for s in scorers}
    out["patient_level"] = {s.name: ev.patient_level(R[s.name], pid, lab) for s in scorers}
    out["subgroup_registration"] = ev.subgroup(R[NewLR.name], y, pid, D.registration, min_patients=8, B=B, seed=seed)
    out["incremental_value"] = uf.incremental_value(D, y, pid, A, fs.INITIAL_COLUMNS, lambda d: cc.design_matrix(d)[0], B=B, seed=seed)
    out["failures"] = {k: v.failures for k, v in R.items() if v.failures}
    return out
