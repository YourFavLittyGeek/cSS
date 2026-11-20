"""shared SYNTHETIC fixtures for the prototype tests"""
import numpy as np, pandas as pd
import _common  # noqa: F401
from uengine import synthetic as sy, experiment as ex, math_component as mc

_CACHE = {}


def cohort(seed=5, n=50, **kw):
    k = (seed, n, tuple(sorted(kw.items())))
    if k not in _CACHE:
        O, E, P = sy.make_cohort(n, seed=seed, **kw); D = ex.population(O)
        pats = sorted(D.patient_key.unique()); tr = D.patient_key.isin(pats[: int(0.75 * len(pats))])
        _CACHE[k] = (D[tr].reset_index(drop=True), D[~tr].reset_index(drop=True), O, E, P)
    return _CACHE[k]


TYPICAL = dict(  # hand-built SYNTHETIC archetypes (values chosen from the generator's invented class means)
    cSS=dict(darkness_z=3.0, edge_contrast=2.6, pial_dist_mm=-0.6, cortex_frac=0.65, tram_frac=0.55, tube_ratio=0.28, surface_alignment=0.78,
             bank_frac=0.6, axis_normal=0.3, vessel_wm_mm=1.0, local_cont_max_mm=3.0, elongation_3d=5.0, volume_mm3=80.0),
    vein=dict(darkness_z=3.4, edge_contrast=2.4, pial_dist_mm=0.9, cortex_frac=0.30, tram_frac=0.12, tube_ratio=0.62, surface_alignment=0.45,
              bank_frac=0.3, axis_normal=0.55, vessel_wm_mm=3.7, local_cont_max_mm=10.0, elongation_3d=8.2, volume_mm3=120.0),
    normal=dict(darkness_z=2.2, edge_contrast=1.6, pial_dist_mm=-1.0, cortex_frac=0.80, tram_frac=0.20, tube_ratio=0.35, surface_alignment=0.6,
                bank_frac=0.5, axis_normal=0.4, vessel_wm_mm=0.6, local_cont_max_mm=2.0, elongation_3d=3.0, volume_mm3=50.0),
    microbleed=dict(darkness_z=3.5, edge_contrast=2.8, pial_dist_mm=-2.0, cortex_frac=0.5, tram_frac=np.nan, tube_ratio=0.5, surface_alignment=0.4,
                    bank_frac=0.3, axis_normal=0.5, vessel_wm_mm=1.0, local_cont_max_mm=2.0, elongation_3d=1.8, volume_mm3=30.0),
    # difficult mimic: a vein with cSS-like darkness / contrast / surface position but tubular and continuing
    mimic_vein=dict(darkness_z=3.0, edge_contrast=2.6, pial_dist_mm=-0.4, cortex_frac=0.55, tram_frac=0.25, tube_ratio=0.62, surface_alignment=0.5,
                    bank_frac=0.4, axis_normal=0.5, vessel_wm_mm=3.0, local_cont_max_mm=11.0, elongation_3d=8.0, volume_mm3=110.0),
)


def row(kind, i=0, **upd):
    r = dict(TYPICAL[kind]) if kind in TYPICAL else {}
    r.update(upd)
    r.update(patient_key="SYNPX", exam_id="SYNPX-E1", obj_index=i, synthetic=True, artifact_zone=0, midline_zone=0, long_structure=0,
             infratentorial=0, rule_version="v4.18", registration=r.get("registration", "ok"), measurement_complete=r.get("measurement_complete", True))
    if all(np.isfinite(mc._f(r, k)) for k in ("darkness_z", "pial_dist_mm")) and "score_v4" not in upd: r["score_v4"] = round(mc.score_v4(r), 2)
    return r


def frame(rows): return pd.DataFrame(rows)


def borderline():
    a, b = TYPICAL["cSS"], TYPICAL["vein"]
    return {k: (a[k] + b[k]) / 2 for k in a}
