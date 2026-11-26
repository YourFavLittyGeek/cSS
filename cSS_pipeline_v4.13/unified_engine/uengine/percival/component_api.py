"""component_api.py - ONE interface implemented by the specialist components ALBUS, NOX and LUMOS (Stage 2 of the consolidation).

Every component answers the same five questions; the PERCIVAL Decision Engine (meta.py) reads its inputs through these contracts instead of
hard-coded columns:

  features(rows, model=None)   the component's evidence for each candidate (arrays; NaN = missing, never a negative)
  version(model=None)          the component's version string (configuration + content hash of its trained part)
  reliability(rows, extras)    per-candidate reliability / uncertainty signals (missing fraction, rule fate, test-time-augmentation spread)
  train(rows, y, g, w, seed)   fit the component's level-0 model with its configuration (frozen family / feature list)
  evaluate(z, y, g)            metrics of the component's log-odds (patient bootstrap CIs)

Engine identifiers stay unchanged (data contracts of saved models): ALBUS -> 'math', NOX -> 'char', LUMOS -> 'image'. 2026-11-25: NOX is ONE
module - its measurement list includes the three uScore measurements x1 / x2 / x5 (gathered into the same per-candidate record); the separate
'unified' input and the Fusion layer were removed (PERCIVAL is the only combiner).
Configurations (frozen families, feature lists) come from the component registry (component_registry.py) and are recorded in every model,
so one component can be frozen, retrained or rolled back while the meta-model is refitted on top (meta.train_cycle(frozen=...)).
"""
import hashlib
import json

import numpy as np

SCHEMA = "percival-component-interface/1.0"


def _h(o): return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:16]


class Component:
    name = ""; engine_inputs = ()

    def config(self, model=None):
        return ((model or {}).get("component_config") or {}).get(self.name) or {}

    def version(self, model=None):
        C = (model or {}).get("components") or {}
        parts = {k: C.get(k) for k in self.engine_inputs if C.get(k) is not None}
        cfg = self.config(model)
        return f"{self.name.lower()}:{cfg.get('registry_version', 'v000')}:{_h(parts) if parts else 'untrained'}"

    def evaluate(self, z, y, g):
        from .meta import metrics
        from ..ml_component import sigmoid
        z = np.asarray(z, float); m = np.isfinite(z)
        return metrics(np.asarray(y)[m], sigmoid(z[m]), np.asarray(g)[m]) if m.sum() >= 5 else dict(n=int(m.sum()))


class Albus(Component):
    """ALBUS - Mathematical Detection: the detector score score_v4 (Platt-recalibrated in the engine) and its rule fate"""
    name = "ALBUS"; engine_inputs = ("math",)

    def features(self, rows, model=None):
        return dict(math=np.array([np.nan if r.get("math") is None else float(r["math"]) for r in rows], float))

    def reliability(self, rows, extras=None):
        """rule fate: review tier 2 (artifact zone / vein-like / microbleed-like / vein evidence > cSS evidence) = less reliable detection"""
        t = np.array([1.0 if str((r.get("albus") or {}).get("review_tier", "")).strip() in ("2", "2.0") else 0.0 for r in rows])
        return dict(albus_tier2=t)

    def train(self, rows, y, g, w, seed=0, **cfg):
        from ..ml_component import MathRecalibration
        return MathRecalibration().fit(self.features(rows)["math"], y, w)


class Nox(Component):
    """NOX - Quantitative MRI Analysis: the candidate's measurements (feature list = the active NOX version, built-in v001 = 9 original
    detector measurements + 18 more detector measurements + uScore x1 / x2 / x5)"""
    name = "NOX"; engine_inputs = ("char",)

    def columns(self, model=None, char_cols=None):
        from .meta import CHAR
        cols = char_cols or ((model or {}).get("features") or {}).get("char") or (((model or {}).get("components") or {}).get("char_cols")) or CHAR
        return list(cols)

    def features(self, rows, model=None, char_cols=None):
        from .meta import X_of
        return dict(char=X_of(rows, self.columns(model, char_cols), "char"))

    def reliability(self, rows, extras=None, char_cols=None):
        X = self.features(rows, char_cols=char_cols)["char"]
        return dict(nox_missing=(~np.isfinite(X)).mean(1) if X.size else np.zeros(len(rows)))

    def train(self, rows, y, g, w, seed=0, kind="logistic", char_cols=None, **cfg):
        from . import learners as LR
        cc = self.columns(char_cols=char_cols)
        return LR.fit_tabular(kind, self.features(rows, char_cols=cc)["char"], y, g, w, cc, seed)


class Lumos(Component):
    """LUMOS - Visual Intelligence: the PERCIVAL image network on the candidate's surface-aligned MRI patch"""
    name = "LUMOS"; engine_inputs = ("image",)

    def features(self, rows, model=None):
        from .meta import maps_of
        M, have = maps_of(rows); return dict(image=M, have=have)

    def reliability(self, rows, extras=None):
        sp = None if extras is None else extras.get("image_spread")
        sp = np.full(len(rows), np.nan) if sp is None else np.asarray(sp, float)
        return dict(lumos_spread=sp)

    def train(self, rows, y, g, w, seed=0, kind="cnn", epochs=30, **cfg):
        from .meta import _fit_image
        F = self.features(rows); h = F["have"]
        return _fit_image(kind, F["image"][h], np.asarray(y)[h], np.asarray(g)[h], seed, epochs)


ALBUS, NOX, LUMOS = Albus(), Nox(), Lumos()
INTERFACES = dict(ALBUS=ALBUS, NOX=NOX, LUMOS=LUMOS)
RELIABILITY = ("albus_tier2", "nox_missing", "lumos_spread")          # learned-uncertainty inputs of the meta-model (meta.py stack_unc)


def reliability_table(rows, extras=None, char_cols=None):
    """the three components' reliability signals for each row (NaN spread when no image output)"""
    out = {}
    out.update(ALBUS.reliability(rows)); out.update(NOX.reliability(rows, char_cols=char_cols)); out.update(LUMOS.reliability(rows, extras))
    return out


def describe(model=None):
    """the interface record of every component for a model (System page / model record)"""
    out = {}
    for n, c in INTERFACES.items():
        d = dict(engine_inputs=list(c.engine_inputs), version=c.version(model), config=c.config(model), interface=SCHEMA)
        if n == "NOX": d["columns"] = dict(measurements=c.columns(model))
        out[n] = d
    return out
