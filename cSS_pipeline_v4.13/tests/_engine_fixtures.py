"""synthetic engine rows for the Stage 2-6 tests (SYNTHETIC ONLY - never real-data performance)."""
import numpy as np

from uengine.percival.meta import CHAR, PREDICTORS


def rows(n_pat=16, per=12, seed=0, extra=None, maps=False, test_frac=0.0, signal=1.2, missing_char=0.0, tier2=0.0):
    """patients with per candidates; y ~ Bernoulli(0.35); CHAR / predictors shifted by `signal` for cSS. extra: {name: shift}"""
    r = np.random.default_rng(seed); out = []
    for p in range(n_pat):
        test = p < int(round(test_frac * n_pat))
        for c in range(per):
            y = int(r.random() < 0.35)
            ch = {k: float(r.normal(signal * y * (1 if i % 2 else -1), 1.0)) for i, k in enumerate(CHAR)}
            if missing_char and r.random() < missing_char: ch = {k: None for k in CHAR}
            for k, sh in (extra or {}).items(): ch[k] = float(r.normal(sh * y, 1.0))
            pr = {k: float(r.normal(0.6 * signal * y, 1.0)) for k in PREDICTORS}
            m = r.normal(0, 0.3, (3, 49, 25)).astype(np.float32) if maps else None
            if maps and y: m[0, 20:29, 8:17] -= 0.8
            out.append(dict(study=f"S{p:02d}", patient=f"P{p:02d}", cand_id=c + 1, y=y, test=test, math=float(r.normal(0.8 * y, 1.0)),
                            char=ch, pred=pr, maps=m, hemi="L" if c % 2 else "R",
                            albus=dict(review_tier="2" if r.random() < tier2 else "1")))
    return out
