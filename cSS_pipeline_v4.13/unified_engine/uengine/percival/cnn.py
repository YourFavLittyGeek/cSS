"""cnn.py - Percival Image ML: a small convolutional network that reads the candidate's MRI patch PIXELS (not a feature table).
Pure numpy (no PyTorch dependency: the shared 'css' environment of the production pipeline is not changed); CPU; deterministic seeds.

Input per candidate: the surface-aligned patch (u along the candidate x v across the surface x n outward, 0.5 mm) reduced to 3 maps of
size U x V: (1) minimum-intensity projection along n of the SWI normalised to the patch median (dark blooming), (2) mean along n,
(3) the fraction of the candidate's own voxels along n (its footprint). Invalid voxels are excluded before normalising.
Network: conv 3x3 x8 -> ReLU -> max-pool 2 -> conv 3x3 x16 -> ReLU -> global average + max pool -> dense -> logit.
Training: Adam, L2, class-balanced weights, flip augmentation along u (the only symmetric axis), early stopping on a patient-held-out
validation split. Output: logit of P(cSS | image patch)."""
import numpy as np

IN_SHAPE = (3, 49, 25)


def patch_maps(a):
    """surface-aligned patch arrays -> (3, U, V) float32 maps, or None if the patch has no valid SWI"""
    swi, val, om = a["image_swi"].astype(np.float32), a["valid_swi"].astype(bool), a["object_mask"].astype(bool)
    if not val.any(): return None
    ref = float(np.median(swi[val]));  ref = ref if ref > 0 else 1.0
    z = np.where(val, swi / ref, np.nan)
    import warnings
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)                  # columns without valid voxels -> NaN -> neutral 1.0 below
        mn = np.nanmin(z, axis=2); me = np.nanmean(z, axis=2)
    mn = np.nan_to_num(mn, nan=1.0); me = np.nan_to_num(me, nan=1.0); fp = om.mean(axis=2)
    M = np.stack([np.clip(mn, 0, 2) - 1, np.clip(me, 0, 2) - 1, fp]).astype(np.float32)
    if M.shape != IN_SHAPE:                                             # pad / crop to the fixed size (centred)
        out = np.zeros(IN_SHAPE, np.float32)
        for c in range(3):
            h, w = min(M.shape[1], IN_SHAPE[1]), min(M.shape[2], IN_SHAPE[2])
            oh, ow = (IN_SHAPE[1] - h) // 2, (IN_SHAPE[2] - w) // 2; ih, iw = (M.shape[1] - h) // 2, (M.shape[2] - w) // 2
            out[c, oh:oh + h, ow:ow + w] = M[c, ih:ih + h, iw:iw + w]
        M = out
    return M


def _im2col(X, k=3):
    N, C, H, W = X.shape; P = np.pad(X, ((0, 0), (0, 0), (1, 1), (1, 1)))
    cols = np.empty((N, C, k, k, H, W), X.dtype)
    for i in range(k):
        for j in range(k): cols[:, :, i, j] = P[:, :, i:i + H, j:j + W]
    return cols.transpose(0, 4, 5, 1, 2, 3).reshape(N * H * W, C * k * k)


def _col2im(dcols, shape, k=3):
    N, C, H, W = shape; d = dcols.reshape(N, H, W, C, k, k).transpose(0, 3, 4, 5, 1, 2); P = np.zeros((N, C, H + 2, W + 2), dcols.dtype)
    for i in range(k):
        for j in range(k): P[:, :, i:i + H, j:j + W] += d[:, :, i, j]
    return P[:, :, 1:-1, 1:-1]


class SmallCNN:
    def __init__(self, seed=0, f1=8, f2=16):
        r = np.random.default_rng(seed); C = IN_SHAPE[0]
        he = lambda fan: np.sqrt(2.0 / fan)
        self.p = dict(W1=(r.standard_normal((C * 9, f1)) * he(C * 9)).astype(np.float32), b1=np.zeros(f1, np.float32),
                      W2=(r.standard_normal((f1 * 9, f2)) * he(f1 * 9)).astype(np.float32), b2=np.zeros(f2, np.float32),
                      W3=(r.standard_normal((2 * f2, 1)) * he(2 * f2)).astype(np.float32), b3=np.zeros(1, np.float32))
        self.seed = seed; self.history = []

    def _forward(self, X):
        N, C, H, W = X.shape; p = self.p; c = {}
        c["X1"] = _im2col(X); z1 = c["X1"] @ p["W1"] + p["b1"]; a1 = np.maximum(z1, 0).reshape(N, H, W, -1).transpose(0, 3, 1, 2); c["z1"] = z1
        H2, W2 = H // 2, W // 2; a1c = a1[:, :, :H2 * 2, :W2 * 2]; r = a1c.reshape(N, a1.shape[1], H2, 2, W2, 2)
        m1 = r.max(axis=(3, 5)); c["mask1"] = (r == m1[:, :, :, None, :, None]); c["a1shape"] = a1.shape
        c["X2"] = _im2col(m1); z2 = c["X2"] @ p["W2"] + p["b2"]; a2 = np.maximum(z2, 0).reshape(N, H2, W2, -1); c["z2"] = z2
        gap, gmp = a2.mean(axis=(1, 2)), a2.max(axis=(1, 2)); c["a2"] = a2
        f = np.concatenate([gap, gmp], 1); c["f"] = f; c["m1shape"] = m1.shape
        return (f @ p["W3"] + p["b3"]).ravel(), c

    def logit_tta(self, X):
        """v5.23 test-time augmentation: mean logit of the patch and its u-flip (the training augmentation) and half their gap
        (an image-model uncertainty: a prediction that changes when the patch is mirrored is not stable)"""
        a, b = self.logit(X), self.logit(np.asarray(X)[:, :, ::-1, :]); return (a + b) / 2, np.abs(a - b) / 2

    def logit(self, X, batch=256): return np.concatenate([self._forward(X[i:i + batch])[0] for i in range(0, len(X), batch)]) if len(X) else np.zeros(0)

    def _grads(self, X, y, w, l2):
        N = len(X); p = self.p; lg, c = self._forward(X)
        pr = 1 / (1 + np.exp(-np.clip(lg, -30, 30))); d = (w * (pr - y) / w.sum())[:, None].astype(np.float32)
        g = dict(W3=c["f"].T @ d + l2 * p["W3"], b3=d.sum(0)); df = d @ p["W3"].T
        f2 = p["W2"].shape[1]; a2 = c["a2"]; Hh, Ww = a2.shape[1], a2.shape[2]
        da2 = np.broadcast_to(df[:, None, None, :f2] / (Hh * Ww), a2.shape).copy()
        mx = a2.max(axis=(1, 2), keepdims=True); da2 += (a2 == mx) * df[:, None, None, f2:]
        dz2 = (da2.reshape(-1, f2)) * (c["z2"] > 0)
        g["W2"] = c["X2"].T @ dz2 + l2 * p["W2"]; g["b2"] = dz2.sum(0)
        dm1 = _col2im(dz2 @ p["W2"].T, c["m1shape"])
        N_, F1, H2, W2_ = c["m1shape"]; da1 = np.zeros(c["a1shape"], np.float32)
        up = c["mask1"] * dm1[:, :, :, None, :, None]; da1[:, :, :H2 * 2, :W2_ * 2] = up.reshape(N_, F1, H2 * 2, W2_ * 2)
        dz1 = da1.transpose(0, 2, 3, 1).reshape(-1, F1) * (c["z1"] > 0)
        g["W1"] = c["X1"].T @ dz1 + l2 * p["W1"]; g["b1"] = dz1.sum(0)
        loss = float(-(w * (y * np.log(pr + 1e-9) + (1 - y) * np.log(1 - pr + 1e-9))).sum() / w.sum())
        return g, loss

    def fit(self, X, y, groups, epochs=40, lr=3e-3, l2=1e-4, batch=64, patience=6, val_frac=0.2):
        """early stopping on a patient-held-out validation split (no patient in both)"""
        X = np.asarray(X, np.float32); y = np.asarray(y, np.float32); g = np.asarray(groups).astype(str); r = np.random.default_rng(self.seed)
        u = np.unique(g); vu = set(r.choice(u, max(1, int(round(val_frac * len(u)))), replace=False)) if len(u) >= 4 else set()
        va = np.isin(g, list(vu)); tr = ~va
        if len(np.unique(y[tr])) < 2: raise ValueError("both classes are needed to train the image network")
        pi = y[tr].mean(); wts = np.where(y == 1, 0.5 / max(pi, 1e-3), 0.5 / max(1 - pi, 1e-3)).astype(np.float32)
        m = {k: np.zeros_like(v) for k, v in self.p.items()}; v2 = {k: np.zeros_like(v) for k, v in self.p.items()}; t = 0
        best, best_p, bad = np.inf, None, 0; idx = np.where(tr)[0]
        for ep in range(epochs):
            r.shuffle(idx)
            for s in range(0, len(idx), batch):
                b = idx[s:s + batch]; Xb = X[b].copy(); flip = r.random(len(b)) < 0.5; Xb[flip] = Xb[flip][:, :, ::-1, :]
                gr, _ = self._grads(Xb, y[b], wts[b], l2); t += 1
                for k in self.p:
                    m[k] = 0.9 * m[k] + 0.1 * gr[k]; v2[k] = 0.999 * v2[k] + 0.001 * gr[k] ** 2
                    self.p[k] -= (lr * (m[k] / (1 - 0.9 ** t)) / (np.sqrt(v2[k] / (1 - 0.999 ** t)) + 1e-8)).astype(np.float32)
            if va.any() and len(np.unique(y[va])) == 2:
                lv = self.logit(X[va]); pv = 1 / (1 + np.exp(-np.clip(lv, -30, 30)))
                vl = float(-(wts[va] * (y[va] * np.log(pv + 1e-9) + (1 - y[va]) * np.log(1 - pv + 1e-9))).sum() / wts[va].sum())
                self.history.append(dict(epoch=ep + 1, val_loss=vl))
                if vl < best - 1e-4: best, best_p, bad = vl, {k: v.copy() for k, v in self.p.items()}, 0
                else:
                    bad += 1
                    if bad >= patience: break
        if best_p is not None: self.p = best_p
        return self

    def to_json(self): return dict(type="cnn", arch="SmallCNN(conv3x3x8-pool-conv3x3x16-gap+gmp-dense)", in_shape=list(IN_SHAPE), seed=self.seed,
                                   params={k: v.tolist() for k, v in self.p.items()}, history=self.history)

    @classmethod
    def from_json(cls, d):
        m = cls(d.get("seed", 0)); m.p = {k: np.array(v, np.float32) for k, v in d["params"].items()}; m.history = d.get("history", []); return m
