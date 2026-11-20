"""image_model.py - Stage 2 IMAGE stream, option A (D1): image-derived patch features + L2-penalised multinomial logistic regression.
numpy / scipy only; local; no network. SYNTHETIC-trained models only in this prototype.

patch_features(arrays, meta, phase_sign) -> {feature: value} from one css-patch/2.0 patch (no label, no detector score, no truth)
study_phase_sign(patches)               the study's typical dark-object phase sign (assumed paramagnetic); makes phase vendor-agnostic
ImageModel.fit(X, y, groups, ...)       softmax over object kinds, balanced class weights, L2; patient-bootstrap ensemble for intervals
ImageModel.predict(X)                   class probabilities, p(cSS) + 5-95 % interval, category
save(path) / load(path) / health(path)  hash-protected file with model card; health: ok / incompatible / corrupt / missing
Categories (as Stage 1): likely_cSS p >= 0.7 and interval above 0.5; unlikely_cSS p <= 0.3 and interval below 0.5; uncertain otherwise and
always when quality flags fire. A category is a reading aid, never a decision."""
import datetime, hashlib, json, os
import numpy as np
from scipy import ndimage as ndi
from scipy.optimize import minimize
from .. import ENGINE_VERSION
from . import IMAGING_VERSION
from .geometry import canonical_json

MODEL_SCHEMA = "css-image-model/1.0"
PATCH_SCHEMA = "css-patch/2.0"
CSS = "css"
NSTEP = 0.5                                                        # surface patch grid spacing (mm)
FEATURES = ["log_obj_vox", "in_mean_z", "in_min_z", "in_p10_z", "contrast", "u_ext_mm", "v_ext_mm", "n_ext_mm", "sheet_ratio", "elong",
            "pial_sd_center_mm", "n_prof_below", "n_prof_center", "n_prof_above", "dark_frac_patch", "valid_frac",
            "phase_para", "phase_sd", "phase_missing", "lab_cortex", "lab_wm", "lab_csf", "lab_none", "labels_missing",
            "flair_rel", "flair_missing", "nat_slices", "nat_inplane_mm", "nat_min_z", "nat_valid_frac"]
FEATURE_SET_HASH = hashlib.sha256(json.dumps(FEATURES).encode()).hexdigest()
QUALITY_MIN_VALID = 0.5


def _ext(idx, axis):
    return float((idx[:, axis].max() - idx[:, axis].min() + 1) * NSTEP) if len(idx) else np.nan


def object_phase(arrays):
    if "image_phase" not in arrays: return np.nan
    om = arrays["object_mask"] & arrays["valid_phase"]
    return float(np.mean(arrays["image_phase"][om])) if om.any() else np.nan


def study_phase_sign(patch_list):
    """sign that makes the study's typical dark object positive (most dark objects on SWI are paramagnetic: veins, haemosiderin)"""
    v = [x for x in (object_phase(a) for a in patch_list) if np.isfinite(x)]
    if not v or abs(float(np.median(v))) < 1e-6: return 1.0, False
    return float(np.sign(np.median(v))), True


def patch_features(a, meta, phase_sign=1.0):
    swi, val = a["image_swi"], a["valid_swi"]; om = a["object_mask"] & val
    ref = float(np.median(swi[val])) if val.any() else np.nan
    z = swi / ref if ref and np.isfinite(ref) and ref > 0 else swi * np.nan
    f = dict.fromkeys(FEATURES, np.nan); idx = np.argwhere(om)
    f["valid_frac"] = float(val.mean()); f["log_obj_vox"] = float(np.log1p(om.sum()))
    if om.any():
        zi = z[om]; f.update(in_mean_z=float(zi.mean()), in_min_z=float(zi.min()), in_p10_z=float(np.percentile(zi, 10)))
        d = ndi.distance_transform_edt(~om, sampling=NSTEP); shell = val & (d > 1.0) & (d <= 3.0)
        if shell.any(): f["contrast"] = float(zi.mean() / max(float(z[shell].mean()), 1e-6))
        f.update(u_ext_mm=_ext(idx, 0), v_ext_mm=_ext(idx, 1), n_ext_mm=_ext(idx, 2))
        f["sheet_ratio"] = f["v_ext_mm"] / max(f["n_ext_mm"], NSTEP); f["elong"] = f["u_ext_mm"] / max(f["v_ext_mm"], NSTEP)
    f["pial_sd_center_mm"] = float(meta.get("pial_sd_at_center_mm", np.nan))
    cu, cv, cn = [s // 2 for s in swi.shape]
    col = z[max(cu - 4, 0):cu + 5, max(cv - 2, 0):cv + 3, :]; cval = val[max(cu - 4, 0):cu + 5, max(cv - 2, 0):cv + 3, :]
    prof = np.array([np.nanmean(np.where(cval[..., k], col[..., k], np.nan)) if cval[..., k].any() else np.nan for k in range(swi.shape[2])])
    f["n_prof_below"] = float(np.nanmean(prof[:cn - 2])) if np.isfinite(prof[:cn - 2]).any() else np.nan
    f["n_prof_center"] = float(np.nanmean(prof[cn - 2:cn + 3])) if np.isfinite(prof[cn - 2:cn + 3]).any() else np.nan
    f["n_prof_above"] = float(np.nanmean(prof[cn + 3:])) if np.isfinite(prof[cn + 3:]).any() else np.nan
    f["dark_frac_patch"] = float((z[val] < 0.6).mean()) if val.any() else np.nan
    if "image_phase" in a and (a["object_mask"] & a["valid_phase"]).any():
        ph = a["image_phase"][a["object_mask"] & a["valid_phase"]]
        f.update(phase_para=float(ph.mean() * phase_sign), phase_sd=float(ph.std()), phase_missing=0.0)
    else: f["phase_missing"] = 1.0
    if "image_labels" in a and om.any():
        L = a["image_labels"][om]
        f.update(lab_cortex=float(np.isin(L, (3, 42)).mean()), lab_wm=float(np.isin(L, (2, 41)).mean()), lab_csf=float((L == 24).mean()),
                 lab_none=float((L == 0).mean()), labels_missing=0.0)
    else: f["labels_missing"] = 1.0
    if "image_flair" in a and (a["object_mask"] & a["valid_flair"]).any():
        fv = a["valid_flair"]; fl = a["image_flair"]; m = a["object_mask"] & fv
        f.update(flair_rel=float(fl[m].mean() / max(float(np.median(fl[fv])), 1e-6)), flair_missing=0.0)
    else: f["flair_missing"] = 1.0
    nm, nv, ns = a["native_object_mask"], a["native_valid_swi"], a["native_swi"]
    f["nat_slices"] = float(nm.any(axis=(1, 2)).sum()); f["nat_valid_frac"] = float(nv.mean())
    if nm[2].any():
        r = np.argwhere(nm[2]); f["nat_inplane_mm"] = float(max(np.ptp(r[:, 0]), np.ptp(r[:, 1])) + 1) * 0.5
    nref = float(np.median(ns[nv])) if nv.any() else np.nan
    if (nm & nv).any() and nref > 0: f["nat_min_z"] = float(ns[nm & nv].min() / nref)
    return f


def matrix(rows):
    return np.array([[r.get(k, np.nan) for k in FEATURES] for r in rows], float)


# ---------------------------------------------------------------- model
def _softmax(Z):
    Z = Z - Z.max(1, keepdims=True); E = np.exp(Z); return E / E.sum(1, keepdims=True)


def _fit_softmax(X, Y, sw, l2):
    n, p = X.shape; K = Y.shape[1]

    def fg(theta):
        W = theta[:K * p].reshape(K, p); b = theta[K * p:]
        P = _softmax(X @ W.T + b); lp = np.log(np.clip(P, 1e-12, 1))
        loss = -float((sw[:, None] * Y * lp).sum()) / sw.sum() + 0.5 * l2 * float((W ** 2).sum())
        G = (sw[:, None] * (P - Y)) / sw.sum()
        return loss, np.concatenate([(G.T @ X + l2 * W).ravel(), G.sum(0)])
    r = minimize(fg, np.zeros(K * p + K), jac=True, method="L-BFGS-B", options=dict(maxiter=2000))
    return r.x[:K * p].reshape(K, p), r.x[K * p:]


class ImageModel:
    def __init__(self, classes=None, l2=0.05, n_boot=20, seed=0):
        self.classes = list(classes or []); self.l2 = l2; self.n_boot = n_boot; self.seed = seed
        self.mu = self.sd = self.W = self.b = None; self.boot = []; self.card = {}

    def _prep(self, X):
        X = np.asarray(X, float); X = np.where(np.isfinite(X), X, self.mu); return (X - self.mu) / self.sd

    def fit(self, X, y, groups):
        X = np.asarray(X, float); y = np.array([str(v) for v in y]); groups = np.asarray(groups)
        self.classes = [str(c) for c in (self.classes or sorted(set(y), key=lambda c: (c != CSS, c)))]
        self.mu = np.nanmean(X, 0); self.mu = np.where(np.isfinite(self.mu), self.mu, 0.0)
        Xi = np.where(np.isfinite(X), X, self.mu); self.sd = Xi.std(0); self.sd = np.where(self.sd > 1e-9, self.sd, 1.0)
        Z = (Xi - self.mu) / self.sd
        Y = np.array([[c == k for k in self.classes] for c in y], float)
        def weights(yy): cnt = {c: (yy == c).sum() for c in set(yy)}; return np.array([len(yy) / (len(cnt) * cnt[c]) for c in yy])
        self.W, self.b = _fit_softmax(Z, Y, weights(y), self.l2)
        rng = np.random.default_rng(self.seed); pats = np.unique(groups); self.boot = []
        for _ in range(self.n_boot):
            pick = rng.choice(pats, size=len(pats), replace=True); ix = np.concatenate([np.where(groups == g)[0] for g in pick])
            self.boot.append(_fit_softmax(Z[ix], Y[ix], weights(y[ix]), self.l2))
        return self

    def proba(self, X, W=None, b=None):
        return _softmax(self._prep(X) @ (self.W if W is None else W).T + (self.b if b is None else b))

    def predict(self, X, quality_flags=None):
        P = self.proba(X); ci = self.classes.index(CSS)
        B = np.array([self.proba(X, W, b)[:, ci] for W, b in self.boot]) if self.boot else P[:, ci][None]
        lo, hi = np.percentile(B, 5, axis=0), np.percentile(B, 95, axis=0); out = []
        for i in range(len(P)):
            pc = float(P[i, ci]); flags = list((quality_flags or [[]] * len(P))[i])
            cat = "uncertain"
            if not flags:
                if pc >= 0.7 and lo[i] > 0.5: cat = "likely_cSS"
                elif pc <= 0.3 and hi[i] < 0.5: cat = "unlikely_cSS"
            k = int(np.argmax(P[i]))
            out.append(dict(p_css=round(pc, 4), p_css_interval=[round(float(lo[i]), 4), round(float(hi[i]), 4)], category=cat,
                            predicted_class=self.classes[k], confidence=round(float(P[i, k]), 4), quality_flags=flags,
                            class_probabilities={c: round(float(P[i, j]), 4) for j, c in enumerate(self.classes)}))
        return out

    # ---------------- persistence
    def params(self):
        return dict(schema=MODEL_SCHEMA, features=FEATURES, feature_set_hash=FEATURE_SET_HASH, patch_schema=PATCH_SCHEMA, classes=self.classes,
                    l2=self.l2, n_boot=self.n_boot, seed=self.seed, mu=np.round(self.mu, 10).tolist(), sd=np.round(self.sd, 10).tolist(),
                    W=np.round(self.W, 10).tolist(), b=np.round(self.b, 10).tolist(),
                    boot=[[np.round(W, 10).tolist(), np.round(b, 10).tolist()] for W, b in self.boot],
                    imaging_version=IMAGING_VERSION, engine_version=ENGINE_VERSION, training=self.card.get("training", {}))

    def save(self, path, card):
        if os.path.exists(path): raise FileExistsError(f"{path} exists - models are never overwritten")
        self.card = card; P = self.params(); h = content_hash(P, card)
        with open(path, "w") as f: json.dump(dict(params=P, model_hash=h, card=card), f, indent=1)
        return h

    @classmethod
    def from_params(cls, P, card):
        m = cls(P["classes"], P["l2"], P["n_boot"], P["seed"])
        m.mu, m.sd, m.W, m.b = (np.array(P[k], float) for k in ("mu", "sd", "W", "b"))
        m.boot = [(np.array(W, float), np.array(b, float)) for W, b in P["boot"]]; m.card = card; return m


def content_hash(params, card):
    """sha256 over the parameters AND the model card (evaluation numbers, data kind, intended use are tamper-evident too)"""
    return hashlib.sha256((canonical_json(params) + "|" + canonical_json(card)).encode()).hexdigest()


def health(path):
    """-> dict(status ok / incompatible / corrupt / missing, reasons, name, version, data_kind, model_hash, card)"""
    if not os.path.exists(path): return dict(status="missing", reasons=["no file"], path=path)
    try:
        with open(path) as f: J = json.load(f)
        P, h, card = J["params"], J["model_hash"], J["card"]
    except Exception as e: return dict(status="corrupt", reasons=[f"unreadable: {type(e).__name__}"], path=path)
    out = dict(path=path, name=card.get("name"), version=card.get("version"), data_kind=card.get("data_kind"), model_hash=h, card=card, reasons=[])
    if content_hash(P, card) != h: return dict(out, status="corrupt", reasons=["content (parameters or card) does not match model_hash"])
    if P.get("schema") != MODEL_SCHEMA: out["reasons"].append(f"model schema {P.get('schema')} != {MODEL_SCHEMA}")
    if P.get("feature_set_hash") != FEATURE_SET_HASH or P.get("features") != FEATURES: out["reasons"].append("feature set differs from this engine")
    if P.get("patch_schema") != PATCH_SCHEMA: out["reasons"].append(f"patch schema {P.get('patch_schema')} != {PATCH_SCHEMA}")
    if str(P.get("imaging_version", "")).split("/")[-1].split(".")[0] != IMAGING_VERSION.split("/")[-1].split(".")[0]:
        out["reasons"].append(f"imaging version {P.get('imaging_version')} incompatible with {IMAGING_VERSION}")
    if card.get("data_kind") != (P.get("training") or {}).get("data_kind"): out["reasons"].append("card data_kind differs from the hash-protected training record")
    if CSS not in P.get("classes", []): out["reasons"].append("model has no cSS class")
    return dict(out, status="incompatible" if out["reasons"] else "ok")


def load(path):
    h = health(path)
    if h["status"] != "ok": raise ValueError(f"model {path} not usable: {h['status']} ({'; '.join(h['reasons'])})")
    with open(path) as f: J = json.load(f)
    return ImageModel.from_params(J["params"], J["card"]), h


def now(): return datetime.datetime.now().isoformat(timespec="seconds")
