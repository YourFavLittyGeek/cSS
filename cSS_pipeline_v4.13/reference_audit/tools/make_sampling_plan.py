"""Rebuilds EXCLUDED_OBJECT_SAMPLING.csv (stratum counts + allocation; no object ids, no labels) from a validation run's
all_objects_full_table.csv.  usage: python reference_audit/tools/make_sampling_plan.py <all_objects_full_table.csv> <out.csv> [--per-mechanism 30]
Allocation: per exclusion mechanism min(30, N); spread over size bins in proportion to N, at least min(3, N_h) per bin.
Column exact_upper95_if_0_found = 1 - 0.05^(1/n) for the mechanism total (one-sided exact bound when no cSS is found)."""
import sys, os, numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")); import ra_common as R
a = sys.argv[1:]; PER = int(a[a.index("--per-mechanism") + 1]) if "--per-mechanism" in a else 30
O = pd.read_csv(a[0], low_memory=False); X = O[O.fate == "excluded"].copy()
X["mechanism"] = [R.category(r) for r in X.excl_reason]; X["size_bin"] = R.size_bin(X.volume_mm3)
X["read_before"] = ~X.label.isin(["unread", "unread_zero"])
g = X.groupby(["mechanism", "size_bin"]).agg(population_N=("obj_id", "size"), studies=("study_id", "nunique"), dev_N=("cohort", lambda s: (s == "dev").sum()),
                                              heldout_N=("cohort", lambda s: (s == "heldout").sum()), already_read_unblinded=("read_before", "sum")).reset_index()
rows = []
for mech, gg in g.groupby("mechanism"):
    gg = gg.reset_index(drop=True); Np = gg.population_N.to_numpy().astype(int).copy(); tot = min(PER, Np.sum())
    al = np.maximum(np.minimum(Np, 3), np.floor(tot * Np / Np.sum())).astype(int).copy()
    while al.sum() > tot: al[np.argmax(al - np.minimum(Np, 3))] -= 1
    while al.sum() < tot: al[np.argmax(Np - al)] += 1
    for i, ((_, r), n) in enumerate(zip(gg.iterrows(), al)):
        rows.append(dict(r, n=int(min(n, r.population_N)), weight_N_over_n=round(r.population_N / n, 2) if n else None,
                         exact_upper95_if_0_found_in_mechanism=round(1 - 0.05 ** (1 / tot), 3) if i == 0 else None))
S = pd.DataFrame(rows); S["source"] = "rule-excluded objects of the current lists (counts only)"
for gate, mech in (("G1 volume", "volume gate"), ("G2 slices", "slice gate"), ("G3 elongation", "elongation gate"), ("G4 no cortex", "no cortex gate")):
    S = pd.concat([S, pd.DataFrame([dict(mechanism=mech, size_bin="all", n=PER, exact_upper95_if_0_found_in_mechanism=round(1 - 0.05 ** (1 / PER), 3),
                                         source=f"work/ID_dropped.csv {gate}: population counted by inventory.py on the Mac; spread over size bins by sample.py")])])
S.to_csv(a[1], index=False); print(f"{len(X)} rule-excluded objects -> plan with {int(S[S.size_bin != 'all'].n.sum())} rule + {4 * PER} gate objects -> {a[1]}")
