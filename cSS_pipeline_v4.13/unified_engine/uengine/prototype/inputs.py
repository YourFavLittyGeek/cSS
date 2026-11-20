"""inputs.py - explicit validation of candidate tables before any component sees them.

sanitize(df) -> (clean DataFrame, InputReport)
  - required key columns: patient_key, exam_id, cand_key (built from exam_id + obj_index / cand_id when absent)
  - duplicate cand_key -> refused (InputError)
  - numeric columns of the schema: strings / bools / objects that do not parse -> NaN with status 'corrupt'; +-inf -> NaN 'corrupt';
    finite values outside the hard valid range -> kept for the record but marked 'out_of_range' (components treat them as missing)
  - forbidden predictor columns (labels, ids, scores, model outputs) are NOT removed (MATH needs score_v4) but are listed; the learned
    component's column list is checked separately (data_validation.assert_predictors_allowed)
  - synthetic guard: data_kind must be 'synthetic' and every row synthetic=True with SYN identifiers (this workspace never scores real data)"""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from .. import feature_schema as fs

KEYS = ("patient_key", "exam_id")


class InputError(ValueError): pass


@dataclass
class InputReport:
    n_rows: int
    corrupt: dict = field(default_factory=dict)          # column -> count of unparseable / infinite values
    out_of_range: dict = field(default_factory=dict)     # column -> count
    missing_columns: list = field(default_factory=list)  # schema-measured columns absent from the table (for the declared inputs)
    forbidden_present: list = field(default_factory=list)
    status: dict = field(default_factory=dict)           # (cand_key, column) -> 'corrupt' | 'out_of_range'


def assert_synthetic(df, data_kind):
    if data_kind != "synthetic": raise InputError(f"data_kind {data_kind!r}: this prototype runs on SYNTHETIC data only")
    if not len(df): return
    if "synthetic" not in df.columns or not df["synthetic"].fillna(False).astype(bool).all():
        raise InputError("table is not marked synthetic on every row")
    for k in KEYS:
        if k in df.columns and not df[k].astype(str).str.startswith("SYN").all(): raise InputError(f"{k}: non-synthetic identifier")


def sanitize(df, needed=fs.INITIAL_FEATURES + ["volume_mm3", "score_v4"], data_kind="synthetic", require_synthetic=True):
    """require_synthetic=False is used ONLY by the deterministic display path (shadow.py) - never for fitting or ML prediction"""
    if not isinstance(df, pd.DataFrame): raise InputError("input must be a pandas DataFrame")
    if require_synthetic: assert_synthetic(df, data_kind)
    d = df.copy().reset_index(drop=True)
    for k in KEYS:
        if k not in d.columns: raise InputError(f"missing key column {k}")
    if "cand_key" not in d.columns:
        idx = d["obj_index"] if "obj_index" in d.columns else (d["cand_id"] if "cand_id" in d.columns else pd.Series(range(len(d))))
        d["cand_key"] = d["exam_id"].astype(str) + "#" + idx.astype(str)
    dup = d["cand_key"][d["cand_key"].duplicated()].tolist()
    if dup: raise InputError(f"duplicate candidate keys: {dup[:5]}")
    rep = InputReport(len(d))
    rep.forbidden_present = [c for c in d.columns if fs.is_forbidden_predictor(c) and c not in ("patient_key", "exam_id", "cand_key")]
    numeric = [c for c in fs.measured() + ["score_v4", "css_evidence", "vein_evidence"] if c in d.columns]
    rep.missing_columns = [c for c in needed if c not in d.columns and c not in fs.TRANSFORMS]
    for c in numeric:
        raw = d[c]
        num = pd.to_numeric(raw, errors="coerce").astype(float)
        bad = (raw.notna() & num.isna()) | np.isinf(num.to_numpy())
        if bad.any():
            rep.corrupt[c] = int(bad.sum())
            for k in d.loc[bad, "cand_key"]: rep.status[(k, c)] = "corrupt"
        num = num.where(~np.isinf(num), np.nan)
        if c in fs.SCHEMA:
            s = fs.SCHEMA[c]; oor = num.notna() & ((num < s.lo) | (num > s.hi))
            if oor.any():
                rep.out_of_range[c] = int(oor.sum())
                for k in d.loc[oor, "cand_key"]: rep.status[(k, c)] = "out_of_range"
        d[c] = num
    return d, rep
