"""feature_schema.py - exact classification of every column the production detector writes (review/ID_candidates.csv; the
excluded list has the same columns plus excl_id / reason / exclusion_confidence), and the prespecified initial ML feature set.

ROLES
  identifier   row / location identifiers - never predictors
  label        reader decision fields - never predictors
  math_output  outputs of the deterministic MATH system (score_v3/v4, css/vein evidence) - MATH component, never characteristics
  rule_flag    binary / categorical decisions made by fixed rules from other columns (tiers, *_zone flags, classes) - MATH side
  model_output outputs of a LEARNED model (v5.10 confidence: confidence_pct / _why / conf_guard) - PAST EXPERIENCE, never predictors
  quality      data-quality / missing-input indicators - quality channel of the fusion interface (not cSS evidence)
  provenance   versions, configuration, status text - never predictors
  categorical  anatomical categories (region name, aparc label code) - not in the initial model (high cardinality, n small)
  deprecated   measured but known invalid (saturates / uninformative) - never predictors
  measured     genuinely measured candidate property - eligible as CHARACTERISTICS

Units: mm, mm3, frac (0-1 share of the object's voxels), sd (noise / local-SD units), ratio (dimensionless >= 0), cos (|cosine|,
0-1 unless signed), count, deg, vox (voxels). Valid ranges are HARD physical / definitional limits used to detect corrupt
values, not plausibility windows. Missingness meanings: 'structural' (not measurable by design for this object, e.g. tram_frac
needs >= 5 rays), 'input' (an input image / anatomy is absent), 'none_expected' (NaN would be a defect).
Source: scripts/detect_css.py, css_features.py, css_vessel.py, css_shape.py, mimic_rules.py (snapshot sha in SOURCE_PROVENANCE.md)."""
from dataclasses import dataclass
import numpy as np

INF = float("inf")


@dataclass(frozen=True)
class Col:
    name: str
    role: str
    family: str = ""
    unit: str = ""
    lo: float = -INF
    hi: float = INF
    missing: str = "none_expected"
    note: str = ""


def _m(name, family, unit, lo=-INF, hi=INF, missing="none_expected", note=""):
    return Col(name, "measured", family, unit, lo, hi, missing, note)


FRAC = (0.0, 1.0)
_C = [
    # identifiers / labels / provenance
    Col("cand_id", "identifier", note="rank in the shown list (changes with every detection)"),
    Col("vox_i", "identifier", note="centroid voxel index (part of the call fingerprint)"),
    Col("vox_j", "identifier"), Col("vox_k", "identifier"),
    Col("accept", "label", note="reader decision field in the list"),
    Col("qc_status", "provenance", note="case QC status text; enters the quality channel, not the evidence"),
    Col("rule_version", "provenance", note="fate: ruleset version (shown) or the exclusion rule id (E1..E30)"),
    Col("feature_qc_flags", "provenance"), Col("feature_schema_version", "provenance"),
    Col("v53_active", "provenance", note="CSS_V53 switch state"), Col("merge_gap_mm", "provenance", note="detector configuration"),
    Col("tier_reason", "provenance", note="text"), Col("review_priority_reason", "provenance", note="text"),
    Col("mimic_reason", "provenance", note="text"), Col("struct_verdict", "provenance", note="text"),
    Col("confidence_why", "model_output", note="text explanation of confidence_pct"),
    # categorical anatomy
    Col("hemi", "categorical", note="L / R"), Col("region", "categorical", note="aparc region name"),
    Col("label", "categorical", note="aparc label CODE (an integer category, not a quantity)"),
    Col("end_type_max", "categorical", "vessel"), Col("end_type_min", "categorical", "vessel"),
    # MATH outputs
    Col("score", "math_output", note="= score_v4 unless CSS_RANK=v3"), Col("score_v3", "math_output"),
    Col("score_v4", "math_output", note="untrained definition score (detect_css.py)"),
    Col("css_evidence", "math_output", note="mean of 5 rule-based cSS terms (0-1)"),
    Col("vein_evidence", "math_output", note="mean of 5 rule-based vein terms (0-1)"),
    # rule flags (fixed functions of other columns / maps)
    Col("artifact_zone", "rule_flag", note="region name in ARTIFACT_ZONES"), Col("midline_zone", "rule_flag", note="median midline distance < 5 mm"),
    Col("vein_like", "rule_flag", note="pial_dist > 0.3 and tube_ratio > 0.4"), Col("long_structure", "rule_flag", note="n_slices x slice > 40 mm"),
    Col("near_ich_suggest", "rule_flag", note="ich_dist_mm <= 5"), Col("infratentorial", "rule_flag"),
    Col("cmb_like", "rule_flag", note="extent <= 10 mm and >= 50 % parenchymal shell (AJNR 2016 rule)"),
    Col("flair_bright", "rule_flag"), Col("flair_ctx_bright", "rule_flag"),
    Col("review_tier", "rule_flag"), Col("review_priority_rank", "rule_flag"), Col("review_priority", "rule_flag"),
    Col("mixed_object", "rule_flag", note="css_pieces: pieces disagree"), Col("mixed_object_review", "rule_flag"),
    Col("single_slice", "rule_flag", note="passed the mm slice gate with < 2 slices"),
    Col("piece_sheet", "rule_flag", note="E22 decision per first-pass piece"),
    Col("struct_cls", "rule_flag", note="BALL / TUBE / RIBBON / OTHER / UNRESOLVED from struct_* by fixed cut-offs"),
    Col("mimic_class", "rule_flag"), Col("mimic_score", "rule_flag", note="rule-based mimic score (mimic_rules.py), not a measurement"),
    Col("soft_gate_fail", "rule_flag", note="generation gate failed (CSS_SOFT_GATES=1)"),
    # learned model outputs
    Col("confidence_pct", "model_output", note="v5.10 learned confidence (css_confidence); feeds E30"),
    Col("conf_guard", "model_output", note="side guard undid E30 for this object"),
    # quality
    Col("missing_t1_anatomy", "quality", unit="0/1"), Col("missing_flair_features", "quality", unit="0/1"),
    Col("missing_phase_features", "quality", unit="0/1"), Col("ref_valid_frac", "quality", unit="frac", lo=0, hi=1),
    Col("mirror_valid_frac", "quality", unit="frac", lo=0, hi=1), Col("phase_valid_frac", "quality", unit="frac", lo=0, hi=1, missing="input"),
    Col("region_n_vox", "quality", unit="count", lo=0),
    # deprecated
    Col("vein_tree_mm", "deprecated", "vessel", "mm", note="merges brain-wide on real SWI (255 mm for most objects)"),
    Col("mirror_dark_frac", "deprecated", "mirror", "frac", note="uninformative; venous anatomy asymmetric"),
    Col("branch_per10mm", "deprecated", "vessel", note="superseded by local_branch_per10mm"),
    # ---- measured: size
    _m("volume_mm3", "size", "mm3", 0), _m("n_slices", "size", "count", 1), _m("extent_mm", "size", "mm", 0),
    _m("n_pieces", "size", "count", 1), _m("path_length_mm", "size", "mm", 0, missing="structural", note="< 3 voxels"),
    _m("equivalent_sphere_diameter_mm", "size", "mm", 0), _m("piece_vol_vox", "size", "vox", 0),
    _m("ext_major_mm", "size", "mm", 0), _m("ext_piece_max_mm", "size", "mm", 0, missing="structural"),
    # ---- measured: shape (coordinate geometry)
    _m("elongation", "shape", "ratio", 0), _m("elongation_3d", "shape", "ratio", 0, missing="structural", note="< 4 voxels"),
    _m("flatness_3d", "shape", "ratio", 0, missing="structural"), _m("compactness_3d", "shape", "ratio", 0, 1, "structural"),
    _m("sphericity", "shape", "ratio", 0, 1, "structural"), _m("tortuosity", "shape", "ratio", 1, missing="structural", note="NaN if end-to-end <= 1 mm"),
    _m("struct_s1_mm", "shape", "mm", 0, missing="structural", note="regrown 3-D structure (<= 20 mm wider window)"),
    _m("struct_s2_mm", "shape", "mm", 0, missing="structural"), _m("struct_s3_mm", "shape", "mm", 0, missing="structural"),
    _m("struct_thick_mm", "shape", "mm", 0, missing="structural"),
    _m("cand_radius_med_mm", "shape", "mm", 0, missing="structural"), _m("cand_radius_p95_mm", "shape", "mm", 0, missing="structural"),
    _m("cand_radius_cv", "shape", "ratio", 0, missing="structural"),
    # ---- measured: image curvature (Hessian) - kept apart from coordinate geometry
    _m("tube_ratio", "hessian", "ratio", 0, 1, "structural", "3-D Hessian tubularity; NaN when not computable"),
    _m("piece_tube", "hessian", "ratio", 0, 1, "structural"),
    _m("sheet3d_med", "hessian", "ratio", missing="structural"), _m("sheet3d_overlap", "hessian", "frac", 0, 1, "structural"),
    # ---- measured: darkness / contrast
    _m("darkness_z", "darkness", "sd", note="positive = darker than the local cortex"),
    _m("darkness_z_p10", "darkness", "sd", missing="structural"), _m("dark_frac_z2", "darkness", "frac", 0, 1, "structural"),
    _m("dark_frac_z3", "darkness", "frac", 0, 1, "structural"), _m("dark_frac_z4", "darkness", "frac", 0, 1, "structural"),
    _m("edge_contrast", "darkness", "sd", missing="structural", note="vs 1-2 mm surroundings"),
    _m("region_z", "darkness", "sd", missing="structural"), _m("region_dark_frac", "darkness", "frac", 0, 1, "structural"),
    _m("dark_cv", "darkness", "ratio", 0, missing="structural"), _m("dark_gap_frac", "darkness", "frac", 0, 1, "structural"),
    _m("minip_len_mm", "darkness", "mm", 0, missing="structural"), _m("minip_cont", "darkness", "frac", 0, 1, "structural"),
    _m("mirror_region_z", "mirror", "sd", missing="structural"), _m("cand_mirror_z", "mirror", "sd", missing="structural"),
    # ---- measured: relation to the cortical surface
    _m("pial_dist_mm", "surface", "mm", -20, 20, note="median signed distance to the labelled pial boundary (- in tissue)"),
    _m("pial_sd_p10_mm", "surface", "mm", -30, 30), _m("pial_sd_p90_mm", "surface", "mm", -30, 30),
    _m("piece_pial_mm", "surface", "mm", -30, 30, "structural"),
    _m("cortex_frac", "surface", "frac", 0, 1), _m("cortex_dist_mm", "surface", "mm", 0),
    _m("surface_contact", "surface", "frac", 0, 1), _m("surface_contact_frac_1mm", "surface", "frac", 0, 1),
    _m("surface_contact_frac_2mm", "surface", "frac", 0, 1), _m("csf_adjacent_frac", "surface", "frac", 0, 1),
    _m("csf_depth_mm", "surface", "mm", 0), _m("parenchyma_frac", "surface", "frac", 0, 1),
    _m("out_frac", "surface", "frac", 0, 1), _m("bank_frac", "surface", "frac", 0, 1, "structural"),
    _m("tram_frac", "surface", "frac", 0, 1, "structural", "tram-track share; NaN when < 5 rays hit (structural)"),
    _m("surface_alignment", "orientation", "cos", 0, 1, "structural"), _m("surface_gradient", "orientation", "ratio", missing="structural"),
    _m("axis_normal", "orientation", "cos", 0, 1, "structural"), _m("axis_angle_deg", "orientation", "deg", 0, 180, "structural"),
    _m("struct_surf_cos", "orientation", "cos", 0, 1, "structural"), _m("struct_ctx_frac", "surface", "frac", 0, 1, "structural"),
    _m("sulcal_depth_mm", "surface", "mm", 0, missing="structural"),
    # ---- measured: vessel continuity
    _m("vessel_wm_mm", "vessel", "mm", 0), _m("vessel_ext_mm", "vessel", "mm", 0), _m("vessel_run_mm", "vessel", "mm", 0, 20),
    _m("cand_geodesic_mm", "vessel", "mm", 0, missing="structural"), _m("local_cont_max_mm", "vessel", "mm", 0, missing="structural"),
    _m("local_cont_min_mm", "vessel", "mm", 0, missing="structural"), _m("local_cont_total_mm", "vessel", "mm", 0, missing="structural"),
    _m("terminal_ends", "vessel", "count", 0, missing="structural"), _m("local_net_mm", "vessel", "mm", 0, missing="structural"),
    _m("local_branch_points", "vessel", "count", 0, missing="structural"), _m("local_branch_per10mm", "vessel", "ratio", 0, missing="structural"),
    _m("net_radius_med_mm", "vessel", "mm", 0, missing="structural"), _m("net_radius_p95_mm", "vessel", "mm", 0, missing="structural"),
    _m("struct_cont", "vessel", "ratio", 0, missing="structural"), _m("piece_vein_frac", "vessel", "frac", 0, 1, "structural"),
    # ---- measured: anatomical location / zones
    _m("rel_height", "location", "ratio", -1, 2, note="0 = floor of the cerebrum, 1 = vertex"),
    _m("infra_frac", "location", "frac", 0, 1), _m("basal_frac", "location", "frac", 0, 1),
    _m("midline_frac", "location", "frac", 0, 1), _m("mask_edge_mm", "location", "mm", 0),
    _m("skull_frac", "location", "frac", 0, 1), _m("vent_frac", "location", "frac", 0, 1),
    _m("plane_dist_mm", "location", "mm", 0, missing="structural"), _m("cos_plane", "location", "cos", 0, 1, "structural"),
    _m("skullbase_frac", "location", "frac", 0, 1), _m("dual_contact_frac", "location", "frac", 0, 1),
    _m("zone2_frac", "location", "frac", 0, 1), _m("sylvian_frac", "location", "frac", 0, 1),
    _m("ich_dist_mm", "location", "mm", 0, 999), _m("ich_contact_frac", "location", "frac", 0, 1),
    # ---- measured: other sequences (input-dependent)
    _m("flair_csf_z", "flair", "sd", missing="input"), _m("flair_ctx_z", "flair", "sd", missing="input"),
    _m("flair_csf_bright_frac", "flair", "frac", 0, 1, "input"),
    _m("phase_z", "phase", "sd", missing="input"), _m("phase_r", "phase", "ratio", missing="input"),
    _m("phase_polarity_frac", "phase", "frac", 0, 1, "input"), _m("mb_cluster_n", "phase", "count", 0, missing="input",
                                                                    note="count of compact parenchymal blobs (mimic_rules)"),
]
SCHEMA = {c.name: c for c in _C}
ROLES = ("identifier", "label", "math_output", "rule_flag", "model_output", "quality", "provenance", "categorical", "deprecated", "measured")
NEVER_PREDICTOR_ROLES = ("identifier", "label", "math_output", "rule_flag", "model_output", "provenance", "deprecated")
# columns that only exist in other files / other steps but must also never be predictors
EXTRA_FORBIDDEN = {"excl_id", "reason", "exclusion_confidence", "drop_id", "gate_id", "score_model", "rank_model",
                   "y", "label_y", "call", "calls", "css_any", "non_css", "gold_neg", "study_id", "exam_id", "patient_key",
                   "confidence_lopo_pct", "p_raw", "p_cal", "fate", "_lab", "_wz", "_excl", "_band"}

# ---------------- where each column is consumed (from the source, verified by tests/test_schema_usage.py)
RULE_USE = {   # exclusion_v4 (MATH) and the generation gates; E30 is PAST EXPERIENCE (learned), listed separately
    "E1": ["infratentorial", "infra_frac"], "E2": ["basal_frac"], "E3": ["rel_height"], "E4": ["extent_mm"],
    "E15": ["skull_frac", "pial_dist_mm"], "E12": [], "E16": ["vent_frac"], "E17": ["out_frac", "cortex_frac", "tram_frac"],
    "E20": ["volume_mm3", "skull_frac"], "E19": ["darkness_z", "skull_frac"], "E21": ["cortex_frac", "skull_frac"],
    "E18": ["edge_contrast"], "E26": ["zone2_frac"], "E27": ["sylvian_frac"], "E28": ["struct_cls", "struct_ctx_frac"],
    "E29": ["struct_cls", "struct_cont", "struct_surf_cos"], "E25": ["dual_contact_frac"], "E13": ["midline_frac"],
    "E22": ["piece_sheet", "plane_dist_mm", "cos_plane", "ext_major_mm"], "E24": ["skullbase_frac"], "E14": ["region", "mask_edge_mm"],
    "E5": ["pial_dist_mm", "tube_ratio", "tram_frac"], "E6": ["vessel_wm_mm", "axis_normal", "tram_frac"],
    "E7": ["cortex_frac", "pial_dist_mm", "tram_frac"], "E8": ["artifact_zone", "rel_height"], "E9": ["edge_contrast"],
    "E10": ["mimic_class", "mimic_score"], "E11": ["mimic_class", "mimic_score"]}
RULE_REASON_ONLY = {"E28": ["struct_s1_mm"], "E29": ["struct_cont"], "E22": ["ext_major_mm", "plane_dist_mm"], "E10": ["mimic_reason"],
                    "E11": ["mb_cluster_n"]}   # read only to word the exclusion reason, not to decide
LEARNED_RULE_USE = {"E30": ["confidence_pct"]}
GATE_USE = {"G0_tiny": ["volume_mm3"], "G1_volume": ["volume_mm3"], "G2_slices": ["n_slices"], "G3_elongation": ["elongation"], "G4_no_cortex": []}
GATE_IDS = ("G0_tiny", "G1_volume", "G2_slices", "G3_elongation", "G4_no_cortex", "legacy")   # gate ids written by detect_css.py
MATH_USE = {
    "score_v4": ["darkness_z", "pial_dist_mm", "tube_ratio", "surface_alignment", "tram_frac", "artifact_zone", "midline_zone",
                 "long_structure", "infratentorial"],
    "css_evidence": ["pial_dist_mm", "tube_ratio", "surface_alignment", "tram_frac", "bank_frac"],
    "vein_evidence": ["tube_ratio", "pial_dist_mm", "surface_alignment", "axis_normal", "vessel_wm_mm"],
    "review_tier": ["artifact_zone", "vein_like", "cmb_like", "css_evidence", "vein_evidence"],
    "review_priority": ["mixed_object", "mimic_class", "cmb_like", "artifact_zone", "tube_ratio", "local_cont_max_mm", "vessel_wm_mm",
                        "end_type_max", "end_type_min", "terminal_ends", "elongation_3d", "pial_dist_mm", "csf_depth_mm", "v53_active", "qc_status"],
}

# ---------------- the prespecified initial learned model (declared BEFORE any evaluation; never selected on data)
# 9 measured characteristics + 1 missingness indicator = 10 input columns (limit: 10).
# Rationale (definition of cSS: curvilinear hypointensity following the cortical surface, often tram-track; main mimics:
# veins - tubular, continuing; artefacts - ill-defined / skull-backed):
#   darkness_z (signal), edge_contrast (well-defined), pial_dist_mm (on the surface), cortex_frac (touches cortex),
#   tram_frac (two banks), tube_ratio (tube vs sheet, image Hessian), elongation_3d (coordinate shape),
#   log_volume (size, log because blooming inflates volume multiplicatively), local_cont_max_mm (vessel continuation),
#   tram_frac_missing (tram-track not measurable is a structural state, not an average value).
INITIAL_FEATURES = ["darkness_z", "edge_contrast", "pial_dist_mm", "cortex_frac", "tram_frac", "tube_ratio", "elongation_3d",
                    "log_volume_mm3", "local_cont_max_mm"]
INITIAL_INDICATORS = {"tram_frac_missing": "tram_frac"}
INITIAL_COLUMNS = INITIAL_FEATURES + list(INITIAL_INDICATORS)
TRANSFORMS = {"log_volume_mm3": ("volume_mm3", lambda v: np.log(np.clip(v, 1.0, None)))}
MAX_INPUT_COLUMNS = 10

# measured columns NOT suitable for the INITIAL model, with the reason (they remain recorded characteristics)
UNSUITABLE_INITIAL = {
    **{c: "input-dependent (FLAIR present in a subset only)" for c in ("flair_csf_z", "flair_ctx_z", "flair_csf_bright_frac")},
    **{c: "input-dependent (phase in 1 of 15 studies)" for c in ("phase_z", "phase_r", "phase_polarity_frac", "mb_cluster_n")},
    **{c: "zone share consumed by a hard exclusion rule: the shown population is truncated on it; location, not lesion character"
       for c in ("infra_frac", "basal_frac", "midline_frac", "skull_frac", "vent_frac", "skullbase_frac", "dual_contact_frac",
                 "zone2_frac", "sylvian_frac", "rel_height", "mask_edge_mm", "plane_dist_mm", "cos_plane")},
    **{c: "regrown-structure measure (audit B8: 20 mm regrowth, unfitted E28/E29); resolution-sensitive" for c in
       ("struct_s1_mm", "struct_s2_mm", "struct_s3_mm", "struct_thick_mm", "struct_cont", "struct_ctx_frac", "struct_surf_cos")},
    **{c: "redundant with a selected size measure (same family, near-deterministic relation)" for c in
       ("n_slices", "extent_mm", "path_length_mm", "equivalent_sphere_diameter_mm", "piece_vol_vox", "ext_major_mm", "ext_piece_max_mm", "n_pieces")},
    **{c: "redundant with a selected darkness measure" for c in ("darkness_z_p10", "dark_frac_z2", "dark_frac_z3", "dark_frac_z4", "region_dark_frac")},
    **{c: "region / mirror reference: known overlap cSS vs normal (v4.19.2), mirror uninformative" for c in ("region_z", "mirror_region_z", "cand_mirror_z")},
    **{c: "redundant with a selected surface measure" for c in ("pial_sd_p10_mm", "pial_sd_p90_mm", "piece_pial_mm", "cortex_dist_mm", "surface_contact",
                                                                   "surface_contact_frac_1mm", "surface_contact_frac_2mm", "parenchyma_frac", "out_frac", "csf_adjacent_frac")},
    **{c: "redundant with local_cont_max_mm (same tracking)" for c in ("local_cont_min_mm", "local_cont_total_mm", "cand_geodesic_mm", "local_net_mm",
                                                                       "local_branch_points", "local_branch_per10mm", "terminal_ends", "net_radius_med_mm", "net_radius_p95_mm", "piece_vein_frac")},
}


def columns_by_role(role):
    return [c.name for c in _C if c.role == role]


def measured():
    return columns_by_role("measured")


def is_forbidden_predictor(name):
    """True for every column that must never enter a model as a predictor (ids, labels, scores, model outputs, flags, text...)"""
    base = name[:-len("_missing")] if name.endswith("_missing") else name
    if name in EXTRA_FORBIDDEN or base in EXTRA_FORBIDDEN: return True
    c = SCHEMA.get(base)
    if c is not None: return c.role in NEVER_PREDICTOR_ROLES
    low = name.lower()
    return any(k in low for k in ("score", "confidence", "rank", "call", "label", "prob", "pred", "_id", "uid", "fingerprint"))


def overlap_matrix(predictors=INITIAL_FEATURES):
    """predictor -> list of MATH elements that already consume the same column (score_v4 / evidence / tiers / exclusion rules)."""
    base = {p: TRANSFORMS[p][0] if p in TRANSFORMS else p for p in predictors}
    out = {}
    for p, b in base.items():
        uses = [k for k, cols in MATH_USE.items() if b in cols] + [r for r, cols in RULE_USE.items() if b in cols]
        uses += [g for g, cols in GATE_USE.items() if b in cols]
        out[p] = uses
    return out
