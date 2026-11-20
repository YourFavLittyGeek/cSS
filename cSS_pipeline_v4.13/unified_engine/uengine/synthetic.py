"""synthetic.py - SYNTHETIC candidate populations laid out like the detector's tables. Software testing only.

Every table carries synthetic=True and identifiers starting with 'SYN'. Nothing here resembles or is derived from a patient.
Generative model (all parameters are invented for testing, NOT estimates of real cSS properties):
  patients            prevalence of cSS among their candidates p_i ~ Beta(a, b) (or fixed), a share of patients cSS-negative
  repeat examinations 1 + Poisson(repeat_rate) exams per patient; exams share the patient's prevalence and a patient signature
  exam effects        scanner darkness offset; registration state (ok / marginal / failed -> no list, as detector exit 5)
  candidates          classes cSS / vein / artifact / normal / microbleed; class-conditional features scaled by `signal`
                      (signal = 0: every class has the same distribution = pure noise)
  MATH                score_v4, evidence, tiers and the E1-E29 fate computed by the VERBATIM detector code (math_component)
  E30                 optional: a share of shown objects excluded by a noisy learned-looking score (rule_version 'E30@v5.10')
  funnel              gate-dropped tiny objects (few columns), cSS lesions never generated (no features)
  labels              reader label = truth with a flip rate; excluded objects labelled only through a declared audit design
  leakage injections  optional columns that copy the label or a model output (for the leakage tests)"""
import numpy as np
import pandas as pd
from . import math_component as mc

CLASSES = ("cSS", "vein", "artifact", "normal", "microbleed")
MIMIX = dict(vein=0.4, normal=0.3, artifact=0.2, microbleed=0.1)
#                        cSS    vein   artif  normal  mb      sd
G = dict(darkness_z=((3.0, 3.4, 4.0, 2.2, 3.5), 0.7),
         edge_contrast=((2.6, 2.4, 1.9, 1.5, 2.8), 0.6),
         pial_dist_mm=((-0.6, 0.9, 1.2, -1.0, -2.0), 0.6),
         cortex_frac=((0.65, 0.30, 0.25, 0.80, 0.50), 0.15),
         tram_frac=((0.50, 0.15, 0.10, 0.20, 0.05), 0.18),
         tube_ratio=((0.30, 0.60, 0.40, 0.35, 0.50), 0.12),
         surface_alignment=((0.75, 0.45, 0.40, 0.60, 0.40), 0.15),
         bank_frac=((0.60, 0.30, 0.20, 0.50, 0.30), 0.15),
         axis_normal=((0.30, 0.55, 0.50, 0.40, 0.50), 0.15),
         log_vessel_wm=((0.0, 1.3, 0.3, -0.5, 0.0), 0.6),
         log_cont=((1.1, 2.3, 1.4, 0.7, 0.7), 0.5),
         log_elong=((1.6, 2.1, 1.4, 1.1, 0.6), 0.35),
         log_vol=((4.4, 4.8, 5.3, 3.9, 3.4), 0.6),
         skull_frac=((0.08, 0.10, 0.45, 0.05, 0.05), 0.08),
         csf_depth_mm=((0.3, 1.0, 0.8, 0.1, 0.0), 0.3),
         minip_cont=((0.7, 0.8, 0.5, 0.4, 0.3), 0.15),
         dark_cv=((0.3, 0.25, 0.4, 0.5, 0.2), 0.1))
TRAM_MISSING = (0.2, 0.4, 0.5, 0.3, 0.7)          # structural missingness of tram_frac by class
CLIP01 = {"cortex_frac", "tram_frac", "tube_ratio", "surface_alignment", "bank_frac", "axis_normal", "skull_frac", "minip_cont"}
MISSABLE = ("darkness_z", "edge_contrast", "pial_dist_mm", "cortex_frac", "tram_frac", "tube_ratio", "elongation_3d", "local_cont_max_mm")
REGIONS = ("ctx-lh-superiorparietal", "ctx-rh-precuneus", "ctx-lh-supramarginal", "ctx-rh-inferiorparietal", "ctx-lh-postcentral",
           "ctx-rh-superiorfrontal", "ctx-lh-lateraloccipital", "ctx-rh-middletemporal")


def _feature(rng, name, ci, signal, mimic_overlap=0.0):
    means, sd = G[name]; mu = means[ci]
    if mimic_overlap and CLASSES[ci] == "vein": mu = mu + mimic_overlap * (means[0] - mu)     # veins pulled toward cSS (difficult mimics)
    m = np.mean(means) + signal * (mu - np.mean(means))
    return rng.normal(m, sd)


def _candidate(rng, cls, signal, dark_offset, reg_noise, mimic_overlap=0.0):
    cls = str(cls); ci = CLASSES.index(cls); f = {k: _feature(rng, k, ci, signal, mimic_overlap) for k in G}
    for k in CLIP01: f[k] = float(np.clip(f[k], 0, 1))
    r = dict(cls=cls, darkness_z=round(f["darkness_z"] + dark_offset, 1), edge_contrast=round(f["edge_contrast"], 2),
             pial_dist_mm=round(f["pial_dist_mm"] + rng.normal(0, reg_noise), 2), cortex_frac=round(f["cortex_frac"], 2),
             tram_frac=round(f["tram_frac"], 2) if rng.random() >= np.mean(TRAM_MISSING) + signal * (TRAM_MISSING[ci] - np.mean(TRAM_MISSING)) else np.nan,
             tube_ratio=round(f["tube_ratio"], 2), surface_alignment=round(f["surface_alignment"], 2), bank_frac=round(f["bank_frac"], 2),
             axis_normal=round(f["axis_normal"], 2), vessel_wm_mm=round(float(np.exp(f["log_vessel_wm"])), 1),
             local_cont_max_mm=round(float(np.exp(f["log_cont"])), 1), elongation_3d=round(float(np.exp(f["log_elong"])), 2),
             volume_mm3=round(float(np.exp(f["log_vol"])), 1), skull_frac=round(f["skull_frac"], 2), csf_depth_mm=round(max(f["csf_depth_mm"], 0), 2),
             minip_cont=round(f["minip_cont"], 2), dark_cv=round(max(f["dark_cv"], 0), 2))
    v = r["volume_mm3"]; el = r["elongation_3d"]
    r["extent_mm"] = round(1.6 * v ** (1 / 3) * np.sqrt(max(el, 1.0)), 1); r["ext_major_mm"] = r["extent_mm"]
    r["n_slices"] = int(max(2, r["extent_mm"] // 2.5)); r["elongation"] = round(el * 0.8, 1)
    r["local_cont_min_mm"] = round(r["local_cont_max_mm"] * rng.uniform(0.2, 0.8), 1)
    r["terminal_ends"] = int(rng.integers(0, 3)); r["minip_len_mm"] = round(r["extent_mm"] * r["minip_cont"], 1)
    r["dark_gap_frac"] = round(float(np.clip(rng.normal(0.15, 0.08), 0, 1)), 2)
    # class-specific constructions below use dc: the true class with probability `signal`, otherwise a class drawn
    # independently of the truth (so signal = 0 makes EVERY column, not only the Gaussian ones, uninformative)
    dc = cls if rng.random() < signal else str(rng.choice(CLASSES))
    # location / zones (artifacts concentrate at the skull base, a few veins at the midline)
    r["rel_height"] = round(float(rng.uniform(0.05, 0.45) if dc == "artifact" else rng.uniform(0.25, 0.98)), 2)
    r["skullbase_frac"] = round(float(rng.uniform(0.1, 0.6)) if dc == "artifact" and rng.random() < 0.4 else 0.0, 2)
    r["midline_frac"] = round(float(rng.uniform(0.5, 0.9)) if dc == "vein" and rng.random() < 0.15 else float(rng.uniform(0, 0.2)), 2)
    r["dual_contact_frac"] = round(float(rng.uniform(0.3, 0.7)) if dc == "vein" and rng.random() < 0.08 else 0.0, 2)
    r["sylvian_frac"] = round(float(rng.uniform(0.2, 0.6)) if dc == "vein" and rng.random() < 0.1 else 0.0, 2)
    for k in ("infra_frac", "basal_frac", "vent_frac"): r[k] = 0.0
    r["infra_frac"] = round(float(rng.uniform(0.3, 0.8)), 2) if dc == "artifact" and rng.random() < 0.15 else 0.0
    r["out_frac"] = round(float(np.clip(0.5 + 0.3 * r["pial_dist_mm"], 0, 1)), 2); r["zone2_frac"] = round(1 - r["out_frac"] * 0.5, 2)
    r["mask_edge_mm"] = round(float(rng.uniform(1, 30)), 1); r["plane_dist_mm"] = round(float(rng.uniform(10, 60)), 1); r["cos_plane"] = round(float(rng.uniform(0, 1)), 2)
    # struct (regrown) measures and classes
    r["struct_cls"] = {"cSS": "RIBBON", "vein": "TUBE", "microbleed": "BALL"}.get(dc, "OTHER") if rng.random() < 0.7 else "UNRESOLVED"
    r["struct_s1_mm"] = round(r["extent_mm"] * 1.2, 1); r["struct_s2_mm"] = round(r["extent_mm"] * float(rng.uniform(0.4, 0.8) if dc == "cSS" else rng.uniform(0.2, 0.55)), 1)
    r["struct_s3_mm"] = round(float(rng.uniform(0.8, 2.5)), 1); r["struct_thick_mm"] = r["struct_s3_mm"]
    r["struct_cont"] = round(float(np.exp(rng.normal(1.2 if dc == "vein" else 0.3, 0.4))), 2)
    r["struct_ctx_frac"] = round(r["cortex_frac"], 2); r["struct_surf_cos"] = round(1 - r["surface_alignment"], 2)
    # rule flags as the detector defines them
    r["infratentorial"] = int(r["infra_frac"] >= 0.6); r["artifact_zone"] = int(dc == "artifact" and rng.random() < 0.4)
    r["midline_zone"] = int(r["midline_frac"] > 0.5); r["long_structure"] = int(r["n_slices"] * 2.5 > 40)
    r["cmb_like"] = int(dc == "microbleed" and r["extent_mm"] <= 10); r["vein_like"] = int(r["pial_dist_mm"] > 0.3 and r["tube_ratio"] > 0.4)
    r["region"] = ("ctx-lh-lateralorbitofrontal" if dc == "artifact" and rng.random() < 0.3 else REGIONS[int(rng.integers(len(REGIONS)))])
    r["hemi"] = "L" if "-lh-" in r["region"] else "R"
    r.update(mimic_class="none", mimic_score=0.0, mb_cluster_n=0, piece_sheet=0, mixed_object=0, end_type_max="", end_type_min="", v53_active=1)
    return r


def make_cohort(n_patients=30, seed=0, signal=1.0, prevalence=("beta", 1.2, 2.0), negative_share=0.25, cands_per_exam=(6, 25),
                repeat_rate=0.3, reader_flip=0.0, reg_fail_rate=0.05, marginal_rate=0.1, e30_rate=0.0, gate_drop=(0, 4),
                not_generated_rate=0.3, audit_mode="audit", confounder=0.0, leak=None, missing_t1_rate=0.0,
                dark_offset_sd=0.3, volume_scale_sd=0.0, extra_missing=0.0, informative_missing=0.0, mimic_overlap=0.0):
    """stress knobs (all off by default; the default random stream is unchanged): dark_offset_sd = scanner darkness offset per exam;
    volume_scale_sd = per-exam log-normal volume / extent scaling (resolution); extra_missing = MCAR share of the 9 initial measures set
    to NaN; informative_missing = extra tram_frac missingness in cSS only (MNAR); mimic_overlap = veins pulled toward cSS (0-1)."""
    """-> (objects DataFrame, exams DataFrame, patients DataFrame). Objects of every fate are included (column fate)."""
    rng = np.random.default_rng(seed)
    engines = {}
    objs, exams, pats = [], [], []
    for pi in range(n_patients):
        pk = f"SYNP{pi:03d}"
        neg = rng.random() < negative_share
        if prevalence[0] == "beta": p_i = 0.0 if neg else float(rng.beta(prevalence[1], prevalence[2]))
        else: p_i = 0.0 if neg else float(prevalence[1])
        conf = rng.normal() if confounder else 0.0                       # patient-level confounder (e.g. field strength)
        if confounder and not neg: p_i = float(np.clip(p_i + 0.25 * confounder * conf, 0, 0.95))
        n_ex = 1 + int(rng.poisson(repeat_rate))
        truth_hemi = {"L": 0, "R": 0}
        for ei in range(n_ex):
            ex = f"{pk}-E{ei + 1}"; shift = rng.choice([0.3, 0.8, 2.5], p=[1 - marginal_rate - reg_fail_rate, marginal_rate, reg_fail_rate])
            reg = "ok" if shift <= 0.5 else ("marginal" if shift <= 1.0 else "failed")
            t1 = rng.random() >= missing_t1_rate
            exams.append(dict(exam_id=ex, patient_key=pk, label_shift_mm=shift, registration=reg, missing_t1_anatomy=int(not t1), synthetic=True))
            if reg == "failed": continue                                    # detector exit 5: no list for this exam
            ctx = mc.ScanContext(T1_ANAT=t1); eng = engines.setdefault(ctx, mc.ExclusionEngine(ctx))
            dark_off = rng.normal(0, dark_offset_sd) + 0.6 * confounder * conf
            vscale = float(np.exp(rng.normal(0, volume_scale_sd))) if volume_scale_sd else 1.0
            n = int(rng.integers(*cands_per_exam))
            for ci in range(n):
                cls = "cSS" if rng.random() < p_i else rng.choice(list(MIMIX), p=list(MIMIX.values()))
                r = _candidate(rng, cls, signal, dark_off, 0.6 if reg == "marginal" else 0.0, mimic_overlap)
                if vscale != 1.0: r["volume_mm3"] = round(r["volume_mm3"] * vscale, 1); r["extent_mm"] = round(r["extent_mm"] * vscale ** (1 / 3), 1)
                r["score_v4"] = round(mc.score_v4(r), 2); ce, ve = mc.evidence(r)
                r["css_evidence"], r["vein_evidence"] = round(ce, 2), round(ve, 2)
                r["review_tier"], r["tier_reason"] = mc.review_tier(r); r["review_priority_rank"] = mc.review_priority(r)[0]
                rv, why = eng.fate(r)
                # characteristic export failures AFTER math / rules were computed (MATH intact; tests the learned part only)
                if extra_missing:
                    for k in MISSABLE:
                        if rng.random() < extra_missing: r[k] = np.nan
                if informative_missing and cls == "cSS" and rng.random() < informative_missing: r["tram_frac"] = np.nan
                r.update(exam_id=ex, patient_key=pk, obj_index=ci, rule_version=rv or "v4.18", reason=why, gate_id="",
                         missing_t1_anatomy=int(not t1), registration=reg, y_true=int(cls == "cSS"), synthetic=True)
                if cls == "cSS" and ei == 0: truth_hemi[r["hemi"]] += 1
                objs.append(r)
            for gi in range(int(rng.integers(*gate_drop)) if gate_drop[1] > 0 else 0):  # gate-dropped tiny objects
                cls = "cSS" if rng.random() < p_i else "normal"
                objs.append(dict(exam_id=ex, patient_key=pk, obj_index=1000 + gi, cls=cls, y_true=int(cls == "cSS"), gate_id="G1_volume",
                                 rule_version="", volume_mm3=round(float(rng.uniform(3, 24)), 1), n_slices=1, hemi=rng.choice(["L", "R"]),
                                 registration=reg, missing_t1_anatomy=int(not t1), synthetic=True, _list="dropped"))
            if p_i > 0 and rng.random() < not_generated_rate:                # a cSS lesion the detector never generated
                h = rng.choice(["L", "R"])
                objs.append(dict(exam_id=ex, patient_key=pk, obj_index=2000, cls="cSS", y_true=1, rule_version="", gate_id="", hemi=h,
                                 registration=reg, missing_t1_anatomy=int(not t1), synthetic=True, _list="missed"))
                if ei == 0: truth_hemi[h] += 1
        g = {h: (0 if c == 0 else (1 if c <= 2 else 2)) for h, c in truth_hemi.items()}
        pats.append(dict(patient_key=pk, n_exams=n_ex, prevalence=p_i, confounder=conf, positive=int(sum(truth_hemi.values()) > 0),
                         grade_L=g["L"], grade_R=g["R"], grade_total=g["L"] + g["R"], synthetic=True))
    O = pd.DataFrame(objs)
    if "_list" not in O.columns: O["_list"] = np.nan
    O["_list"] = O["_list"].fillna(pd.Series(np.where(O["rule_version"].astype(str).str.startswith("E"), "excluded", "candidates"), index=O.index))
    # optional E30: a learned-looking score excludes the lowest shown objects
    if e30_rate > 0:
        sh = O.index[O._list == "candidates"]
        conf_score = O.loc[sh, "score_v4"] + rng.normal(0, 0.3, len(sh))
        cut = np.quantile(conf_score, e30_rate)
        e30 = sh[conf_score < cut]
        O.loc[e30, "rule_version"] = "E30@v5.10"; O.loc[e30, "_list"] = "excluded"
        O.loc[sh, "confidence_pct"] = np.round(100 / (1 + np.exp(-(conf_score - cut) * 2)), 1)
    from .funnel import fate_of
    O["fate"] = [fate_of(l, rv) for l, rv in zip(O._list, O.rule_version)]
    O["measurement_complete"] = O.fate.isin(["shown", "rule_excluded", "learned_excluded"])
    O["rule_id"] = [str(rv).split("@")[0] if f in ("rule_excluded", "learned_excluded") else "" for rv, f in zip(O.rule_version, O.fate)]
    # reader labels: every shown object read (with flip noise); excluded objects only through the audit design; others unlabelled
    y = np.full(len(O), np.nan)
    sh = (O.fate == "shown").to_numpy()
    flip = rng.random(len(O)) < reader_flip
    y[sh] = np.where(flip[sh], 1 - O.y_true[sh], O.y_true[sh])
    from .funnel import review_web_audit_design
    designs = {}
    for ex, g_ in O[O.fate.isin(["rule_excluded", "learned_excluded"])].groupby("exam_id"):
        d = review_web_audit_design(g_.reason.fillna("") if "reason" in g_ else [""] * len(g_), audit_mode); designs[ex] = d
        if d.kind == "census": take = g_.index
        elif d.kind == "srs":
            elig = g_.index[[not str(r).lower().startswith("infratentorial") for r in g_.reason.fillna("")]]
            take = rng.choice(elig, size=min(d.n, len(elig)), replace=False) if len(elig) else []
        else: take = []
        y[np.isin(O.index, take)] = O.y_true[np.isin(O.index, take)]
    O["y"] = y
    if leak == "label_copy": O["leaky_feature"] = O.y_true + rng.normal(0, 0.01, len(O))
    if leak == "model_output":
        O["confidence_pct"] = np.round(100 * (0.8 * O.y_true + 0.2 * rng.random(len(O))), 1); O["copied_conf"] = O.confidence_pct * 1.0
    O.attrs["designs"] = designs
    return O, pd.DataFrame(exams), pd.DataFrame(pats)
