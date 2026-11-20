"""train_image_model.py - trains and evaluates the SYNTHETIC demonstration image model (Stage 2 prototype). Synthetic data only.

cohort_rows(base)    features of every patch of a synthetic cohort + truth kind + consensus label (readers R1 and R2 agree on the same
                     definite class and subtype; indeterminate, insufficient quality and disagreements are NOT training rows)
evaluate(...)        patient-grouped K-fold: p(cSS) AUC (pooled, within-patient), 8-kind accuracy, log loss, Brier, calibration slope
train(out, ...)      train cohort (signal) + independent synthetic test cohort + two NEGATIVE CONTROL cohorts (signal = 0; train on one, test on the
                     other) -> model file with
                     its card; every number in the card describes the invented generator, not cSS."""
import csv, json, os, tempfile
import numpy as np
from . import image_model as IM, patches as PT, synthetic_cohort as C
from .. import SYNTHETIC_STAMP


def cohort_rows(base):
    with open(os.path.join(base, "unified_engine", "image_truth", "cohort.json")) as f: meta = json.load(f)
    with open(os.path.join(base, "unified_engine", "image_truth", "readers.csv"), newline="") as f: R = list(csv.DictReader(f))
    lab = {}
    for r in R: lab.setdefault((r["study_id"], r["list"], int(r["obj_id"])), {})[r["reader_id"]] = r
    rows = []
    for sid in meta["profiles"]:
        with open(os.path.join(base, "unified_engine", "image_truth", f"{sid}.csv"), newline="") as f:
            T = {(t["list"], int(t["obj_id"])): t for t in csv.DictReader(f)}
        E = PT.extract_study(base, sid); sign, _ = IM.study_phase_sign(list(E["patches"].values()))
        for k, a in E["patches"].items():
            f = IM.patch_features(a, json.loads(a["metadata_json"]), sign); t = T[k]
            rd = lab.get((sid, k[0], k[1]), {}); r1, r2 = rd.get("R1"), rd.get("R2")
            cons = None
            if r1 and r2 and r1["primary_class"] == r2["primary_class"] and r1["mimic_subtype"] == r2["mimic_subtype"] \
                    and r1["primary_class"] in ("definite_css", "definite_mimic"):
                cons = "css" if r1["primary_class"] == "definite_css" else r1["mimic_subtype"]
            rows.append(dict(f, study_id=sid, list=k[0], obj_id=k[1], truth=t["kind"], consensus=cons))
    return rows, meta


def _auc(y, s):
    y = np.asarray(y, bool); s = np.asarray(s, float)
    if y.all() or (~y).all(): return None
    from scipy.stats import rankdata
    r = rankdata(s); n1 = y.sum(); n0 = (~y).sum()
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _within_auc(y, s, g):
    num = den = 0.0
    for gg in np.unique(g):
        m = g == gg; yy, ss = np.asarray(y)[m].astype(bool), np.asarray(s)[m]
        if yy.all() or (~yy).all(): continue
        d = ss[yy][:, None] - ss[~yy][None]; num += (d > 0).sum() + 0.5 * (d == 0).sum(); den += d.size
    return float(num / den) if den else None


def _cal_slope(y, p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6); x = np.log(p / (1 - p)); y = np.asarray(y, float); b = np.zeros(2)
    Xd = np.c_[np.ones_like(x), x]
    for _ in range(50):
        mu = 1 / (1 + np.exp(-Xd @ b)); W = mu * (1 - mu) + 1e-9
        step = np.linalg.solve(Xd.T @ (W[:, None] * Xd) + 1e-6 * np.eye(2), Xd.T @ (y - mu)); b += step
        if np.abs(step).max() < 1e-8: break
    return float(b[1])


def metrics(y_kind, P, groups, classes):
    ci = classes.index("css"); pc = P[:, ci]; y = np.array([k == "css" for k in y_kind])
    pred = np.array(classes)[P.argmax(1)]
    return dict(n=int(len(y)), n_css=int(y.sum()), auc_pooled=_auc(y, pc), auc_within_patient=_within_auc(y, pc, np.asarray(groups)),
                kind_accuracy=float((pred == np.asarray(y_kind)).mean()), log_loss=float(-np.mean(np.log(np.clip(np.where(y, pc, 1 - pc), 1e-12, 1)))),
                brier=float(np.mean((pc - y) ** 2)), calibration_slope=_cal_slope(y, pc) if 0 < y.sum() < len(y) else None)


def auc_ci(y_kind, p_css, groups, n_boot=500, seed=0):
    """patient-bootstrap 95 % CI of the pooled p(cSS) AUC"""
    y = np.array([k == "css" for k in y_kind]); s = np.asarray(p_css, float); g = np.asarray(groups); pats = np.unique(g)
    rng = np.random.default_rng(seed); v = []
    for _ in range(n_boot):
        ix = np.concatenate([np.where(g == x)[0] for x in rng.choice(pats, size=len(pats), replace=True)]); a = _auc(y[ix], s[ix])
        if a is not None: v.append(a)
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if v else None


def independent(model, rows):
    """metrics of a fitted model on EVERY scorable object of an independent cohort against the generator's truth (not reader labels),
    with a patient-bootstrap CI"""
    te = list(rows); P = model.proba(IM.matrix(te)); g = [r["study_id"] for r in te]
    m = metrics([r["truth"] for r in te], P, g, model.classes); m["auc_pooled_ci95"] = auc_ci([r["truth"] for r in te], P[:, model.classes.index("css")], g)
    return m


def evaluate(rows, k=5, seed=0, l2=0.05):
    tr = [r for r in rows if r["consensus"]]; g = np.array([r["study_id"] for r in tr]); pats = np.unique(g)
    rng = np.random.default_rng(seed); fold = dict(zip(rng.permutation(pats), np.arange(len(pats)) % k))
    X = IM.matrix(tr); y = np.array([r["consensus"] for r in tr]); classes = sorted(set(y), key=lambda c: (c != "css", c))
    P = np.zeros((len(tr), len(classes)))
    for f in range(k):
        te = np.array([fold[x] == f for x in g])
        if te.all() or not te.any(): continue
        m = IM.ImageModel(classes, l2=l2, n_boot=0).fit(X[~te], y[~te], g[~te]); P[te] = m.proba(X[te])
    return metrics([r["truth"] for r in tr], P, g, classes)


def train(out_path, n_train=48, n_test=16, n_null=24, seed=500, l2=0.05, n_boot=20, workdir=None, version="1.0.0"):
    work = workdir or tempfile.mkdtemp(prefix="uengine_image_train_"); bases = {}
    for name, n, s, sig in (("train", n_train, seed, 1), ("test", n_test, seed + 1, 1), ("null_train", n_null, seed + 2, 0), ("null_test", n_null, seed + 3, 0)):
        bases[name] = os.path.join(work, name); C.write_cohort(bases[name], n=n, seed=s, signal=sig)
    rows, meta = cohort_rows(bases["train"]); test_rows, _ = cohort_rows(bases["test"])
    null_rows, _ = cohort_rows(bases["null_train"]); null_test_rows, _ = cohort_rows(bases["null_test"])
    ntr = [r for r in null_rows if r["consensus"]]
    null_model = IM.ImageModel(l2=l2, n_boot=0, seed=seed).fit(IM.matrix(ntr), np.array([r["consensus"] for r in ntr]), np.array([r["study_id"] for r in ntr]))
    tr = [r for r in rows if r["consensus"]]
    X = IM.matrix(tr); y = np.array([r["consensus"] for r in tr]); g = np.array([r["study_id"] for r in tr])
    model = IM.ImageModel(l2=l2, n_boot=n_boot, seed=seed).fit(X, y, g)
    ev = dict(cv_train_cohort=evaluate(rows, seed=seed, l2=l2),
              independent_synthetic_test=independent(model, test_rows),
              negative_control_independent=independent(null_model, null_test_rows),
              negative_control_cv=evaluate(null_rows, seed=seed, l2=l2),
              note=("negative control: trained on one signal-free cohort, tested on an independent one (CI must contain 0.5); its K-fold CV "
                    "value is reported too but is unstable on small null samples (fold prevalence artefact, Stage 1 finding)"),
              label_noise=dict(train_objects=len(rows), consensus_rows=len(tr),
                               consensus_wrong_vs_truth=int(sum(r["consensus"] != r["truth"] for r in tr))))
    card = dict(name="synthetic_image_softmax", version=version, created=IM.now(), data_kind="synthetic", stamp=SYNTHETIC_STAMP,
                classes=model.classes, n_features=len(IM.FEATURES), method="image-derived css-patch/2.0 features + L2 multinomial logistic "
                "regression (balanced), patient-bootstrap ensemble for intervals (D1 option A)",
                training=dict(data_kind="synthetic", generator=C.COHORT_SCHEMA, seed=seed, n_studies=n_train, n_objects=len(rows),
                              n_training_rows=len(tr), label_source="consensus of simulated readers R1 + R2 (agreed definite class)",
                              class_counts={str(c): int((y == c).sum()) for c in model.classes}, l2=l2, n_boot=n_boot),
                evaluation=ev, intended_use="software testing and GUI demonstration on SYNTHETIC studies only",
                out_of_scope="any real study, any clinical decision, any performance claim")
    h = model.save(out_path, card)
    return dict(path=out_path, model_hash=h, card=card, workdir=work)
