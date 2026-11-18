"""Annotation fields (one source for the CSV templates, the validators and the evaluation).
Allowed values are checked by validate_annotations.py; free text only where stated."""
CATEGORY = ["definite_cSS", "probable_cSS", "non_cSS", "indeterminate"]
NONCSS_TYPE = ["", "cortical_vein", "pial_vessel", "sulcal_vessel", "dural_structure", "skull_base_artifact", "other_susceptibility_artifact",
               "microbleed", "calcification", "normal_dark_cortex", "cSAH_acute", "ICH_related", "other"]
MORPH = ["", "linear_band", "curvilinear_gyriform", "tram_track", "patchy", "dot_like", "tubular", "other"]
CONT = ["", "continuous", "discontinuous", "single_focus"]
APPEAR = ["", "hypointense_band", "hypointense_dot", "blooming", "not_visible", "not_available", "other"]
FLAIR = ["", "normal", "sulcal_hyperintensity", "cortical_hyperintensity", "not_visible", "not_available"]
VASC = ["", "none_seen", "adjacent_vessel", "continuous_with_vessel", "uncertain"]
CONF = ["1", "2", "3", "4", "5"]                     # 1 very low ... 5 certain
HEMI = ["L", "R", "midline"]
LOBE = ["frontal", "parietal", "temporal", "occipital", "insula", "cingulate", "cerebellar", "other"]
LESION_COLUMNS = ["reader_id", "read_session", "patient_id", "lesion_id", "hemisphere", "lobe", "cortical_region", "sulcal_location",
                  "x_mm", "y_mm", "z_mm", "vox_i", "vox_j", "vox_k", "mask_file", "length_mm", "thickness_mm", "n_slices", "morphology",
                  "continuity", "swi_appearance", "gre_appearance", "flair_appearance", "associated_vascular_structure", "confidence_1to5",
                  "final_category", "noncss_type", "uncertainty_reason", "comment", "read_minutes"]
OBJECT_COLUMNS = ["case_id", "patient_id", "reader_id", "read_session", "final_category", "noncss_type", "confidence_1to5", "morphology",
                  "continuity", "associated_vascular_structure", "lesion_extends_beyond_outline", "uncertainty_reason", "comment"]
PATIENT_COLUMNS = ["reader_id", "read_session", "patient_id", "image_quality_1to3", "sequences_available", "css_present_L", "css_present_R",
                   "multifocality_L_0to2", "multifocality_R_0to2", "n_definite", "n_probable", "n_indeterminate", "read_minutes", "comment"]
ALLOWED = dict(final_category=CATEGORY, noncss_type=NONCSS_TYPE, morphology=MORPH, continuity=CONT, swi_appearance=APPEAR,
               gre_appearance=APPEAR, flair_appearance=FLAIR, associated_vascular_structure=VASC, confidence_1to5=CONF, hemisphere=HEMI,
               lesion_extends_beyond_outline=["", "yes", "no", "unsure"])
