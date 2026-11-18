"""Simulation check of the stratified-SRS miss-rate estimator used in evaluate.py (same formulas): bias and 95 % CI coverage.
Population built like the real rejected pool (stratum sizes of EXCLUDED_OBJECT_SAMPLING.csv) with known cSS rates."""
import numpy as np, pandas as pd
from scipy.stats import beta, norm
plan = pd.read_csv(__import__("os").path.join(__import__("os").path.dirname(__file__), "..", "EXCLUDED_OBJECT_SAMPLING.csv"))
plan = plan[pd.to_numeric(plan.population_N, errors="coerce").notna()].copy(); N = plan.population_N.astype(int).to_numpy(); n = plan.n.astype(int).to_numpy()
def cp(k, m): return (0.0 if k == 0 else beta.ppf(.025, k, m - k + 1), 1.0 if k == m else beta.ppf(.975, k + 1, m - k))
rng = np.random.default_rng(1); out = []
for true_rate in (0.0, 0.01, 0.03, 0.10):
    K = rng.binomial(N, true_rate)                               # fixed finite population: K_h cSS objects in stratum h
    truth = K.sum() / N.sum(); est, cov_n, cov_c = [], 0, 0
    for _ in range(4000):
        k = rng.hypergeometric(K, N - K, n)                       # SRS without replacement within each stratum
        p = k / n; T = (N * p).sum(); V = np.where(n > 1, N ** 2 * (1 - n / N) * p * (1 - p) / np.maximum(n - 1, 1), 0).sum()
        lo, hi = max(0, T - 1.96 * np.sqrt(V)) / N.sum(), (T + 1.96 * np.sqrt(V)) / N.sum()
        clo = sum(N[i] * cp(k[i], n[i])[0] for i in range(len(N))) / N.sum(); chi = sum(N[i] * cp(k[i], n[i])[1] for i in range(len(N))) / N.sum()
        est.append(T / N.sum()); cov_n += lo <= truth <= hi; cov_c += clo <= truth <= chi
    out.append(dict(true_rate=true_rate, finite_pop_rate=round(truth, 4), mean_estimate=round(np.mean(est), 4), bias=round(np.mean(est) - truth, 5),
                    coverage_normal=round(cov_n / 4000, 3), coverage_conservative=round(cov_c / 4000, 3)))
print(pd.DataFrame(out).to_string(index=False))
