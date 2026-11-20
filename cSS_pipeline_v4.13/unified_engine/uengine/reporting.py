"""reporting.py - JSON / Markdown writers. Every report produced from synthetic data is stamped SYNTHETIC in its first line and in
a 'synthetic' field; a writer refuses to write a report without an explicit data_kind ('synthetic' is the only kind allowed here)."""
import json, os, datetime
import numpy as np
from . import SYNTHETIC_STAMP

ALLOWED_KINDS = ("synthetic",)


def _clean(o):
    if isinstance(o, dict): return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)): return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.bool_): return bool(o)
    if isinstance(o, np.ndarray): return _clean(o.tolist())
    return o


def write_json(path, obj, data_kind):
    if data_kind not in ALLOWED_KINDS: raise ValueError(f"data_kind {data_kind!r} not allowed in this workspace (only {ALLOWED_KINDS})")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    d = dict(stamp=SYNTHETIC_STAMP, synthetic=True, written=datetime.datetime.now().isoformat(timespec="seconds"), content=_clean(obj))
    with open(path, "w") as f: json.dump(d, f, indent=1)
    return path


def fmt(v, nd=2):
    if v is None: return "-"
    if isinstance(v, float): return "-" if not np.isfinite(v) else f"{v:.{nd}f}"
    return str(v)


def md_table(rows, cols, headers=None):
    h = headers or cols
    L = ["| " + " | ".join(h) + " |", "|" + "---|" * len(h)]
    for r in rows: L.append("| " + " | ".join(fmt(r.get(c)) for c in cols) + " |")
    return "\n".join(L)
