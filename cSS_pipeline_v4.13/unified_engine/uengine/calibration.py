"""calibration.py - calibration assessment and inner-fold recalibration.

calibration_slope_intercept: logistic regression of y on logit(p) (slope; 1 = ideal, < 1 = predictions too extreme) and the
calibration-in-the-large intercept with logit(p) as an OFFSET (0 = ideal). Reliability bins and expected calibration error (ECE).
Platt scaling is fitted only on inner out-of-fold scores of the TRAINING part (fit_platt); it is never fitted on the rows it is
applied to. Every function refuses to report on fewer than min_n rows or min_events events (returns None + reason)."""
import numpy as np
from .ml_component import irls, sigmoid


def _logit(p): p = np.clip(np.asarray(p, float), 1e-9, 1 - 1e-9); return np.log(p / (1 - p))


def calibration_slope_intercept(y, p, min_n=20, min_events=5):
    y = np.asarray(y, float); lp = _logit(p)
    if len(y) < min_n or min(y.sum(), len(y) - y.sum()) < min_events:
        return dict(slope=None, intercept=None, citl=None, reason=f"too few rows / events (n={len(y)}, events={int(min(y.sum(), len(y) - y.sum()))})")
    b, _, _ = irls(lp[:, None], y, 1e-8)
    a0, _, _ = irls(np.zeros((len(y), 0)), y, 0.0, offset=lp)
    return dict(slope=float(b[1]), intercept=float(b[0]), citl=float(a0[0]), reason="")


def reliability(y, p, bins=10):
    y = np.asarray(y, float); p = np.asarray(p, float); edges = np.linspace(0, 1, bins + 1); out = []; ece = 0.0
    for a, b in zip(edges[:-1], edges[1:]):
        m = (p >= a) & ((p < b) if b < 1 else (p <= b))
        if m.any():
            out.append(dict(lo=float(a), hi=float(b), n=int(m.sum()), p_mean=float(p[m].mean()), observed=float(y[m].mean())))
            ece += m.mean() * abs(p[m].mean() - y[m].mean())
    return out, float(ece)


def fit_platt(z_inner_oof, y_inner):
    """(a, b) of sigmoid(a z + b), fitted on inner out-of-fold logits of the training part only"""
    b, _, _ = irls(np.asarray(z_inner_oof, float)[:, None], np.asarray(y_inner, float), 1e-6)
    return float(b[1]), float(b[0])


def apply_platt(z, ab): return sigmoid(ab[0] * np.asarray(z, float) + ab[1])
