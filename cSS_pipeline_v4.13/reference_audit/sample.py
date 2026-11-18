"""Reproducible stratified sampling of production-REJECTED objects for blinded expert review.
usage: python reference_audit/sample.py BATCH_NAME --studies M02,M03,... [--seed 20261119] [--per-stratum 6] [--strata mechanism,size_bin]
       [--include-shown K] [--plan plan.csv]
- population = inventory objects with stage excluded or dropped (+ optionally K shown objects per study as blinded controls, so a
  reviewer cannot infer that every object in a batch was rejected)
- strata = any of: mechanism, size_bin, lobe, confidence_bin (default mechanism x size_bin); --plan CSV (columns = strata + n) overrides
  --per-stratum per stratum
- within each stratum the draw is simple random sampling without replacement (SRS), so each batch - and the union of batches with the
  same strata, because every later draw is SRS from the not-yet-sampled remainder - is a stratified SRS of the inventory: the design that
  evaluate.py's estimator assumes. (There is deliberately no per-study cap: a cap would make inclusion probabilities unequal.)
- objects already in ANY earlier batch (reference_audit/batches/ledger.csv) are never sampled again
- writes reference_audit/batches/<BATCH>/:
    cases_blinded.csv   case_id, study code, voxel/mm centre only (what the reviewer may see)
    key_CONCEALED.csv   case_id -> uid, stage, reason, mechanism, stratum, population size, inclusion probability, score, confidence
    sampling_frame.csv  per stratum: population N, sampled n, weight N/n  (for false-negative-rate estimation)
  and appends the ledger. Nothing in review/ or work/ is touched; no threshold or decision is changed."""
import sys, os, glob, json, time, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ra_common as R

a = sys.argv[1:]
if not a or a[0].startswith("-"): sys.exit(__doc__)
arg = lambda k, d=None: a[a.index(k) + 1] if k in a else d
NAME = a[0]; SEED = int(arg("--seed", 20261119)); PER = int(arg("--per-stratum", 6)); MAXS = 10 ** 9
if "--max-per-study" in a: sys.exit("--max-per-study was removed: it breaks the equal-probability design within strata")
STRATA = arg("--strata", "mechanism,size_bin").split(","); NSHOWN = int(arg("--include-shown", 0))
INV = os.path.join(R.OUT, "inventory"); BD = os.path.join(R.OUT, "batches"); out = os.path.join(BD, NAME)
if os.path.exists(out): sys.exit(f"batch {NAME} exists - choose a new name (batches are never overwritten)")
studies = arg("--studies", "").split(",") if arg("--studies") else sorted({os.path.basename(p).split("_")[0] for p in glob.glob(f"{INV}/*_objects_concealed.csv")})
C = pd.concat([pd.read_csv(f"{INV}/{s}_objects_concealed.csv").merge(pd.read_csv(f"{INV}/{s}_objects_public.csv"), on=["uid", "study_id"]) for s in studies], ignore_index=True)
C["confidence_bin"] = pd.cut(pd.to_numeric(C.get("confidence_pct", np.nan), errors="coerce"), [-1, 10, 20, 30, 50, 101],
                             labels=["<10", "10-20", "20-30", "30-50", ">=50"]).astype(str)
ledger_p = os.path.join(BD, "ledger.csv")
for p in glob.glob(os.path.join(BD, "*", "batch_config.json")):                     # all batches must share the strata definition
    if json.load(open(p)).get("strata") != STRATA: sys.exit(f"{p} used strata {json.load(open(p)).get('strata')} - every batch must use {STRATA} (or start a new audit folder)")
used = set(pd.read_csv(ledger_p).uid) if os.path.exists(ledger_p) else set()
rng = np.random.default_rng(SEED)
pop = C[C.stage.isin(["excluded", "dropped"]) & ~C.uid.isin(used)].copy()
plan = pd.read_csv(arg("--plan")) if arg("--plan") else None
picked, frame = [], []
for key, g in pop.groupby(STRATA, dropna=False):
    key = key if isinstance(key, tuple) else (key,)
    n = PER
    if plan is not None:
        q = plan
        for s_, v in zip(STRATA, key): q = q[q[s_].astype(str) == str(v)]
        n = int(q.n.iloc[0]) if len(q) else 0
        if not len(q) and "size_bin" in STRATA:          # a plan row with size_bin 'all' is spread over the size bins in proportion
            qa = plan[(plan.size_bin.astype(str) == "all")]
            for s_, v in zip(STRATA, key):
                if s_ != "size_bin": qa = qa[qa[s_].astype(str) == str(v)]
            if len(qa):
                others = [s_ for s_ in STRATA if s_ != "size_bin"]
                mask = np.logical_and.reduce([pop[s_].astype(str) == str(v) for s_, v in zip(STRATA, key) if s_ != "size_bin"]) if others else np.ones(len(pop), bool)
                Nm = int(mask.sum()); n = max(min(3, len(g)), int(round(int(qa.n.iloc[0]) * len(g) / Nm))) if Nm else 0
    n = min(n, len(g))
    sel = g.iloc[rng.permutation(len(g))[:n]] if n else g.iloc[:0]
    frame.append(dict(**{s_: v for s_, v in zip(STRATA, key)}, population_N=len(g), sampled_n=n, weight=(len(g) / n) if n else np.nan,
                      already_sampled_before=int(C[C.uid.isin(used)].pipe(lambda x: x[np.logical_and.reduce([x[s_].astype(str) == str(v) for s_, v in zip(STRATA, key)])]).shape[0])))
    picked.append(sel.assign(stratum="|".join(map(str, key)), stratum_N=len(g), inclusion_prob=n / len(g) if len(g) else np.nan))
S = pd.concat(picked, ignore_index=True) if picked else pop.iloc[:0]
if MAXS < 10 ** 9:                                     # cap per study (reading burden), random within study, frame recomputed below
    S = pd.concat([g.iloc[rng.permutation(len(g))[:MAXS]] for _, g in S.groupby("study_id")], ignore_index=True)
if NSHOWN:
    sh = C[(C.stage == "shown") & ~C.uid.isin(used)]
    ctrl = pd.concat([g.iloc[rng.permutation(len(g))[:NSHOWN]] for _, g in sh.groupby("study_id")], ignore_index=True)
    S = pd.concat([S, ctrl.assign(stratum="shown control", stratum_N=np.nan, inclusion_prob=np.nan)], ignore_index=True)
S = S.iloc[rng.permutation(len(S))].reset_index(drop=True)
S.insert(0, "case_id", [f"{NAME}-{i + 1:04d}" for i in range(len(S))])
os.makedirs(out)
S[["case_id", "study_id", "vox_i", "vox_j", "vox_k", "x_mm", "y_mm", "z_mm"]].to_csv(f"{out}/cases_blinded.csv", index=False)
keep = ["case_id", "uid", "study_id", "stage", "production_id", "label_value", "reason", "mechanism", "gate_id", "gate_measured", "gate_threshold",
        "stratum", "stratum_N", "inclusion_prob", "volume_mask_mm3", "size_bin", "lobe", "region", "hemi", "confidence_bin"] + \
       [c for c in ("score_v4", "confidence_pct", "darkness_z", "extent_mm") if c in S.columns]
S[[c for c in keep if c in S.columns]].to_csv(f"{out}/key_CONCEALED.csv", index=False)
F = pd.DataFrame(frame)
if MAXS < 10 ** 9 and len(F):
    cnt = S[S.stage != "shown"].stratum.value_counts()
    F["sampled_n"] = ["|".join(map(str, [r[s_] for s_ in STRATA])) for _, r in F.iterrows()]
    F["sampled_n"] = F.sampled_n.map(cnt).fillna(0).astype(int); F["weight"] = F.population_N / F.sampled_n.replace(0, np.nan)
F.to_csv(f"{out}/sampling_frame.csv", index=False)
json.dump(dict(batch=NAME, seed=SEED, strata=STRATA, per_stratum=PER, plan=arg("--plan"), max_per_study=MAXS, shown_controls=NSHOWN, studies=studies,
               created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), n_cases=len(S)), open(f"{out}/batch_config.json", "w"), indent=1)
led = S[["uid", "case_id", "study_id"]].assign(batch=NAME)
led.to_csv(ledger_p, mode="a", header=not os.path.exists(ledger_p), index=False)
print(f"{NAME}: {len(S)} cases ({(S.stage != 'shown').sum()} rejected objects in {len(F)} strata, {(S.stage == 'shown').sum()} shown controls) -> {out}")
