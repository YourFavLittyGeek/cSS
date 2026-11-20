"""characteristics_component.py - CHARACTERISTICS: measured candidate properties, label-free.

This layer validates and represents measurements; it learns nothing and reads no label. Per candidate it returns every measured
column of the schema with a STATUS:
  ok                 finite value inside the hard valid range
  missing_structural NaN where the schema says the measure is not defined for some objects (e.g. tram_frac with < 5 rays)
  missing_input      NaN because an input sequence is absent (FLAIR / phase)
  missing_unexpected NaN where the schema expects a value (a defect or an incompletely measured object)
  out_of_range       finite but outside the hard valid range -> treated as missing, reported
  not_measured       the object never got this measurement (gate-dropped object, see funnel.py)
Scores, flags, model outputs and identifiers are refused (feature_schema roles); asking for them raises."""
from dataclasses import dataclass, field
import numpy as np
from . import feature_schema as fs


class NotACharacteristic(ValueError): pass


@dataclass
class CharacteristicsEvidence:
    values: dict                       # name -> float (NaN when not usable)
    status: dict                       # name -> status string
    completeness: float                # share of requested measures with status ok
    quality: dict = field(default_factory=dict)   # quality-role columns, passed through for the fusion quality channel


def _num(v):
    try: x = float(v)
    except (TypeError, ValueError): return np.nan
    return x


def check_value(name, v):
    c = fs.SCHEMA[name]; x = _num(v)
    if not np.isfinite(x):
        return np.nan, {"structural": "missing_structural", "input": "missing_input"}.get(c.missing, "missing_unexpected")
    if x < c.lo or x > c.hi: return np.nan, "out_of_range"
    return x, "ok"


def characteristics(row, names=None, measured_complete=True):
    """CharacteristicsEvidence for one detector row. names default = every measured column of the schema.
    measured_complete=False (gate-dropped objects) marks every measure not_measured (never imputed as an ordinary value)."""
    names = list(names) if names is not None else fs.measured()
    bad = [n for n in names if n not in fs.SCHEMA or fs.SCHEMA[n].role != "measured"]
    if bad: raise NotACharacteristic(f"not measured characteristics (role is not 'measured'): {bad}")
    vals, st = {}, {}
    for n in names:
        if not measured_complete: vals[n], st[n] = np.nan, "not_measured"; continue
        vals[n], st[n] = check_value(n, row.get(n, np.nan))
    q = {c: row.get(c) for c in fs.columns_by_role("quality") if c in row}
    ok = sum(s == "ok" for s in st.values())
    return CharacteristicsEvidence(vals, st, ok / max(len(names), 1), q)


def design_row(row, columns=fs.INITIAL_COLUMNS, measured_complete=True):
    """values of the declared model input columns (with transforms and missingness indicators) + statuses.
    Indicators are 1 when their source is not 'ok' for a structural reason, 0 when ok; a value that is missing for any other
    reason (unexpected / out of range / not measured) is left NaN in BOTH the value and the indicator so that it is visible
    (the ML preprocessing then imputes it and records the count)."""
    out, st = {}, {}
    for c in columns:
        if c in fs.INITIAL_INDICATORS.values() or c in fs.SCHEMA:
            v, s = check_value(c, row.get(c, np.nan)) if measured_complete else (np.nan, "not_measured")
            out[c], st[c] = v, s
        elif c in fs.TRANSFORMS:
            src, f = fs.TRANSFORMS[c]
            v, s = check_value(src, row.get(src, np.nan)) if measured_complete else (np.nan, "not_measured")
            out[c], st[c] = (float(f(v)) if s == "ok" else np.nan), s
        elif c in fs.INITIAL_INDICATORS:
            continue
        else:
            raise NotACharacteristic(f"{c}: not a declared input column")
    for ind, src in fs.INITIAL_INDICATORS.items():
        if ind not in columns: continue
        s = st.get(src) or check_value(src, row.get(src, np.nan))[1]
        out[ind] = 1.0 if s == "missing_structural" else (0.0 if s == "ok" else np.nan); st[ind] = "ok" if np.isfinite(out[ind]) else s
    return out, st


def design_matrix(df, columns=fs.INITIAL_COLUMNS, complete_col="measurement_complete"):
    """X (n x len(columns)) + per-column status counts. Rows with measurement_complete == False are all-NaN (not_measured)."""
    X = np.full((len(df), len(columns)), np.nan); counts = {c: {} for c in columns}
    recs = df.to_dict("records")
    for i, r in enumerate(recs):
        comp = bool(r.get(complete_col, True)) if complete_col in r else True
        vals, st = design_row(r, columns, comp)
        for j, c in enumerate(columns):
            X[i, j] = vals[c]; counts[c][st[c]] = counts[c].get(st[c], 0) + 1
    return X, counts
