#!/usr/bin/env python3
"""label_schema.py - candidate label schema css-labels/2.0 and the documented conversion from the existing labels (v5.17, Stage 2 P4).
Research software. Source files are NEVER changed: labels/candidate_labels.csv (css-labels/1.0, expert sheets) and the reviewers' call
files stay as they are; build() writes the DERIVED table labels/candidate_labels_v2.csv (regenerated each time).

css-labels/2.0 primary_class: definite_css | definite_mimic (+ mimic_subtype) | indeterminate | insufficient_quality | out_of_scope
Conversion (approved decision D2, 2026-11-20):
  expert sheet codes (css-labels/1.0, confidence 1-5):
    C -> definite_css if confidence >= 4, else indeterminate
    V VS VC VT VX TV A AM N NI MB CA SAH LN HI -> definite_mimic (subtype = the 1.0 fine label) if confidence >= 4, else indeterminate
    U -> indeterminate;  IS -> out_of_scope (infratentorial);  H -> out_of_scope (ICH-related);  confidence missing -> indeterminate
  reviewer calls (the app's reviewer records an explicit decision without a 1-5 confidence; recorded as confidence 'not recorded'):
    cSS -> definite_css;  Vessel -> definite_mimic / vein_unspecified;  Normal -> definite_mimic / normal_other;
    Artifact -> definite_mimic / artifact_unspecified;  Microbleed -> definite_mimic / microbleed;  Unsure -> indeterminate;
    Near ICH -> out_of_scope (ICH-related)
  v5.17 reviewer fine labels (Quick Add): the reviewer may store a fine code with its call; it is used as the subtype when present.
Every v2 row keeps its source (file, schema, original code / call, reviewer, time) so nothing is reinterpreted silently."""
import glob, os, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import LABELS, norm_call

SCHEMA = "css-labels/2.0"
CLASSES = ("definite_css", "definite_mimic", "indeterminate", "insufficient_quality", "out_of_scope")
SUBTYPES = ["vein_unspecified", "vein_surface", "vein_sulcal", "vein_transcortical", "vein_sinus_adjacent", "thrombosed_vein", "artifact_airbone",
            "artifact_motion", "artifact_unspecified", "normal_other", "normal_iron_cortex", "microbleed", "calcification", "acute_cSAH",
            "laminar_necrosis", "haemorrhagic_infarct"]
CALL_MAP = {"cSS": ("definite_css", ""), "Vessel": ("definite_mimic", "vein_unspecified"), "Normal": ("definite_mimic", "normal_other"),
            "Artifact": ("definite_mimic", "artifact_unspecified"), "Microbleed": ("definite_mimic", "microbleed"), "Unsure": ("indeterminate", ""),
            "Near ICH": ("out_of_scope", "")}
COLS = ["study_id", "list", "obj_id", "cand_uid", "reviewer_id", "session", "primary_class", "mimic_subtype", "confidence", "scope_reason", "quality_reason",
        "time", "source", "source_schema", "source_value", "label_schema_version"]


def from_v1(code, confidence):
    """css-labels/1.0 sheet code (+ confidence) -> (primary_class, mimic_subtype, scope_reason)"""
    if code not in LABELS: raise ValueError(f"unknown 1.0 code {code!r}")
    fine, _ = LABELS[code]
    conf = None if confidence in (None, "") or (isinstance(confidence, float) and confidence != confidence) else int(float(confidence))
    if code == "U": return "indeterminate", "", ""
    if code == "IS": return "out_of_scope", "", "infratentorial"
    if code == "H": return "out_of_scope", "", "ICH-related"
    if conf is None or conf < 4: return "indeterminate", "", ""
    if code == "C": return "definite_css", "", ""
    return "definite_mimic", fine, ""


def from_call(call, fine=""):
    """reviewer call (+ optional v5.17 fine code) -> (primary_class, mimic_subtype, scope_reason)"""
    if call not in CALL_MAP: raise ValueError(f"unknown call {call!r}")
    cls, sub = CALL_MAP[call]
    if call == "Near ICH": return cls, "", "ICH-related"
    if fine and cls == "definite_mimic":
        f = LABELS.get(fine, (fine, ""))[0] if fine in LABELS else fine
        if f in SUBTYPES: sub = f
    return cls, sub, ""


def build(base):
    """-> DataFrame of every label in css-labels/2.0 (expert sheets + every reviewer's calls with their history); written to
    labels/candidate_labels_v2.csv"""
    rows = []
    p = os.path.join(base, "labels", "candidate_labels.csv")
    if os.path.exists(p):
        for _, r in pd.read_csv(p, dtype=str).iterrows():
            try: cls, sub, scope = from_v1(r.get("code"), r.get("confidence"))
            except ValueError: continue
            rows.append(dict(study_id=r.get("study_id"), list=r.get("list"), obj_id=r.get("obj_id"), cand_uid=r.get("cand_uid"), reviewer_id=r.get("reviewer_id"),
                             session=r.get("session"), primary_class=cls, mimic_subtype=sub, confidence=r.get("confidence") or "", scope_reason=scope, quality_reason="",
                             time=r.get("timestamp", ""), source=os.path.relpath(p, base), source_schema="css-labels/1.0", source_value=r.get("code")))
    files = [(p, os.path.basename(p).split("_calls_")[0]) for p in sorted(glob.glob(os.path.join(base, "review", "*_calls_*.csv")))]
    have = {sid for _, sid in files}
    # v5.24: studies reviewed with versions before the per-reviewer files (v5.7) only have the shared review/ID_calls.csv - read it for
    # those studies (reviewer 'earlier version'), never in addition to per-reviewer files (it is their derived effective copy)
    for p in sorted(glob.glob(os.path.join(base, "review", "*_calls.csv"))):
        sid = os.path.basename(p)[:-len("_calls.csv")]
        if sid and sid not in have: files.append((p, sid))
    for p, sid in files:
        try: d = pd.read_csv(p, dtype=str)
        except Exception: continue
        legacy = not os.path.basename(p).startswith(f"{sid}_calls_")
        for _, r in d.iterrows():
            call = norm_call(r.get("call")); call = call.strip() if isinstance(call, str) else call
            if legacy and not isinstance(r.get("reviewer"), str): r = r.copy(); r["reviewer"] = "earlier version (shared calls file)"
            if not isinstance(call, str) or call not in CALL_MAP: continue
            cls, sub, scope = from_call(call, r.get("fine_code") if isinstance(r.get("fine_code"), str) else "")
            uid = f"{sid}:{int(float(r['vox_i']))}:{int(float(r['vox_j']))}:{int(float(r['vox_k']))}:{float(r['volume_mm3']):g}" if all(
                isinstance(r.get(k), str) for k in ("vox_i", "vox_j", "vox_k", "volume_mm3")) else ""
            rows.append(dict(study_id=sid, list="candidate", obj_id=r.get("cand_id"), cand_uid=uid, reviewer_id=r.get("reviewer"), session="", primary_class=cls,
                             mimic_subtype=sub, confidence="not recorded", scope_reason=scope, quality_reason="", time=r.get("time", ""), source=os.path.relpath(p, base),
                             source_schema="reviewer calls", source_value=call + (f" / {r.get('fine_code')}" if isinstance(r.get("fine_code"), str) else "")))
    df = pd.DataFrame(rows, columns=COLS[:-1]); df["label_schema_version"] = SCHEMA
    os.makedirs(os.path.join(base, "labels"), exist_ok=True); df.to_csv(os.path.join(base, "labels", "candidate_labels_v2.csv"), index=False)
    return df


def summary(df):
    return dict(n=int(len(df)), by_class={c: int((df.primary_class == c).sum()) for c in CLASSES}, by_subtype=df[df.primary_class == "definite_mimic"].mimic_subtype.value_counts().to_dict(),
                reviewers=sorted(df.reviewer_id.dropna().unique().tolist()), studies=int(df.study_id.nunique()), schema=SCHEMA)


if __name__ == "__main__":
    B = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project")); d = build(B); print(summary(d))
