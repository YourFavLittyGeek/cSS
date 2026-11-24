"""eligibility.py (v5.24) - the Training Eligibility Engine: ONE place that decides, per reviewed candidate and per learning component,
whether it may be used for training, with reason codes. The training cycle, the dataset manifests and the Training Center screen all use
this module, so what the screen shows is exactly what training uses.

Components and what each needs (besides a usable expert label):
  char    Characteristic ML  at least one of the 9 detector measurements (missing ones are imputed with the training median, recorded)
  image   Image ML           the MRI patch around the candidate (extractable from the study's SWI and candidate mask)
  fusion  Fusion             both of the above
  meta    Percival meta-model + calibration   the label alone (MATH is always present; other sources may be missing - modelled)
  predictor  Unified Score predictor model    at least one RELIABLE Unified Score predictor (v1.1)
  shadow  Shadow evaluation of a candidate model   the label alone; locked-test patients INCLUDED (shadow only evaluates, never learns) (v1.1)
Dataset membership: 'development' (used to learn) or 'locked test' (patients set aside permanently; used only to evaluate)."""

RULES_VERSION = "percival-eligibility/1.4"     # 1.1 (v5.24): + predictor, shadow components; missing requirements in words
                                               # 1.2 (v5.25): patient identity must be verified (no study-code substitution)
                                               # 1.3 (v5.25): task-specific detection & segmentation learning with missed cSS support
                                               # 1.4 (Phase 3A): expert ground truth only - consensus of designated experts / adjudication,
                                               #     provenance class (blind post-3A, verified or adjudicated historical); missed cSS too
COMPONENTS = ("char", "image", "fusion", "meta", "predictor", "shadow", "detection", "segmentation")
LEARNING = ("char", "image", "fusion", "meta", "detection", "segmentation")   # the components trained by the Percival training cycle
NAMES = dict(char="Imaging Features (Charact. ML)", image="MRI Patch (Image ML)", fusion="Integrated Model Evidence",
             meta="Model Adaptation (Meta-model)", predictor="Unified Score predictors", shadow="Shadow evaluation",
             detection="Quantitative Candidate Detection", segmentation="Lesion Segmentation Mask")

REASONS = {
    "NOT_REVIEWED": "no expert call for this candidate",
    "UNCERTAIN": "expert call Unsure - kept, not used for cSS / not-cSS learning",
    "OUT_OF_SCOPE": "expert call Near ICH (out of scope) - kept, not used",
    "CONFLICT": "reviewers disagree (cSS vs not cSS) - needs adjudication (Review › Calls policy) or Settings › use the effective call",
    "STUDY_EXCLUDED": "study left out by you",
    "STUDY_ARCHIVED": "study archived (Settings: archived studies excluded)",
    "DUPLICATE_STUDY": "same examination as another study already used - counted once",
    "NOT_AUTHORIZED": "local learning is switched off for this project",
    "NO_IMAGE": "MRI patch not available (image missing or unreadable)",
    "NO_MEASUREMENTS": "no detector measurements for this candidate",
    "LOCKED_TEST": "patient in the locked test cohort - used only for evaluation",
    "HISTORICAL_LABEL": "label from an earlier version / project review (matched to this candidate by position and volume)",
    "QC_LOW": "study image quality flagged by QC (still used; reported)",
    "NO_PREDICTORS": "no reliable Unified Score predictor (anatomy / registration missing or unreliable)",
    "UNRECOGNISED_CALL": "expert call not recognised by this version (kept, listed in Data integrity)",
    "PATIENT_ID_MISSING": "no patient identity record for this study - patient-level validation is impossible (study-code substitution is refused)",
    "PATIENT_ID_UNVERIFIED": "patient identity not verified (study registered as one patient per study without confirmation) - confirm it in Training Center › Patient identity",
    "PATIENT_ID_CONFLICT": "possible identity conflict: the same examination fingerprint / DICOM study belongs to another patient record",
    "NO_MASK": "no 2D contour or 3D segmentation mask available for segmentation learning",
    "NO_EXPERT": "no call by a designated expert (trainee / other / unknown reviewers never decide)",
    "ABSTAINED": "the expert calls are all Unsure (abstention) - unresolved",
    "INSUFFICIENT_QUORUM": "fewer definite expert calls than the consensus rule requires - unresolved",
    "NOT_PRIMARY_GROUND_TRUTH": "label not eligible as primary ground truth (blinding unknown, AI visible, or not an independent review) - verify or adjudicate",
    "REVIEWER_NOT_EXPERT": "missed cSS marked by a reviewer who is not a designated expert",
    "REVIEW_NEEDS_REPAIR": "a reviewer file of this study does not match its journal - labels withheld until repaired",
}
REQUIREMENTS = dict(NOT_REVIEWED="an expert call (cSS or not cSS)", UNCERTAIN="a definite call (cSS or not cSS)", OUT_OF_SCOPE="a definite call",
                    CONFLICT="agreement between reviewers or an adjudicated call", NO_IMAGE="the MRI patch (SWI + candidate mask)",
                    NO_MEASUREMENTS="detector measurements", NO_PREDICTORS="a reliable Unified Score predictor (FreeSurfer anatomy + registration)",
                    NOT_AUTHORIZED="local learning switched on", UNRECOGNISED_CALL="a call this version recognises",
                    PATIENT_ID_MISSING="a patient identity record", PATIENT_ID_UNVERIFIED="a verified patient identity (import grouping or your confirmation)",
                    PATIENT_ID_CONFLICT="a resolved patient identity conflict",
                    NO_MASK="a valid 2D contour or 3D segmentation mask", NO_EXPERT="a call by a designated expert",
                    ABSTAINED="a definite expert call or an adjudication", INSUFFICIENT_QUORUM="more definite expert calls or an adjudication",
                    NOT_PRIMARY_GROUND_TRUTH="a blind expert read, a documented verification or an adjudication",
                    REVIEWER_NOT_EXPERT="an expert's mark", REVIEW_NEEDS_REPAIR="the reviewer file repaired from its journal")


def evaluate(c):
    """c: dict(label y (1/0/None), label_kind ('css'|'mimic'|'uncertain'|'out_of_scope'|None), conflict, historical, study_excluded,
    study_archived, duplicate, authorized, has_image, n_char, test, qc, has_mask). -> dict(status, reasons, components {k: dict(ok, reasons)}, partition)"""
    reasons, block = [], None
    kind = c.get("label_kind")
    if kind is None: block = "NOT_REVIEWED"
    elif kind == "uncertain": block = "UNCERTAIN"
    elif kind == "out_of_scope": block = "OUT_OF_SCOPE"
    elif kind == "unrecognised": block = "UNRECOGNISED_CALL"
    elif c.get("conflict"): block = "CONFLICT"
    if block is None and c.get("gt_block"): block = c["gt_block"]           # 1.4: expert ground truth (call_ledger status / provenance)
    for flag, code in (("study_excluded", "STUDY_EXCLUDED"), ("study_archived", "STUDY_ARCHIVED"), ("duplicate", "DUPLICATE_STUDY")):
        if c.get(flag) and block is None: block = code
    if not c.get("authorized", True) and block is None: block = "NOT_AUTHORIZED"
    idn = c.get("identity", "verified")             # v5.25: verified | declared | assumed | unconfirmed | missing | conflict
    if block is None and idn not in ("verified", "declared"):
        block = {"missing": "PATIENT_ID_MISSING", "conflict": "PATIENT_ID_CONFLICT"}.get(idn, "PATIENT_ID_UNVERIFIED")
    if c.get("historical"): reasons.append("HISTORICAL_LABEL")
    if c.get("qc") == "insufficient_quality": reasons.append("QC_LOW")
    comp = {}
    for k in COMPONENTS:
        r = [block] if block else []
        if not block:
            if k in ("image", "fusion") and not c.get("has_image"): r.append("NO_IMAGE")
            if k in ("char", "fusion") and not c.get("n_char"): r.append("NO_MEASUREMENTS")
            if k == "predictor" and not c.get("has_predictors", True): r.append("NO_PREDICTORS")
            if k == "segmentation" and not c.get("has_mask", True): r.append("NO_MASK")
        comp[k] = dict(ok=not r, reasons=r, missing=[REQUIREMENTS[x] for x in r if x in REQUIREMENTS])
    status = ("not_reviewed" if block == "NOT_REVIEWED" else "needs_adjudication" if block == "CONFLICT" else
              "unrecognised" if block == "UNRECOGNISED_CALL" else
              "identity_unverified" if block in ("PATIENT_ID_MISSING", "PATIENT_ID_UNVERIFIED", "PATIENT_ID_CONFLICT") else
              "excluded" if block else "eligible")
    if status == "eligible" and c.get("test"): reasons.append("LOCKED_TEST")
    return dict(status=status, reasons=([block] if block else []) + reasons, components=comp,
                partition=None if status != "eligible" else ("test" if c.get("test") else "development"))


def explain(codes): return [REASONS.get(x, x) for x in codes]
