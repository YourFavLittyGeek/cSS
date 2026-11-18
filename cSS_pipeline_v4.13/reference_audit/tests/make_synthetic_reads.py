"""TEST ONLY: synthetic reader files on the PH3 / PH6 phantoms (from the phantom truth). Never use on patient data."""
import sys, os, numpy as np, pandas as pd, nibabel as nib
from scipy import ndimage as ndi
B, PK, BATCHES = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
W = f"{B}/reference_audit/whole_scan/{PK}"; key = pd.read_csv(f"{W}/key_CONCEALED.csv"); rows = {"R1": [], "R2": []}
for r in key.itertuples():
    T = np.asarray(nib.load(f"{B}/work/{r.study_id}_truth.nii.gz").dataobj)
    for i, lab in enumerate([l for l in np.unique(T) if l > 0], 1):
        c = np.round(ndi.center_of_mass(T == lab)).astype(int)
        b = dict(read_session="1", patient_id=r.case_code, lesion_id=str(i), hemisphere="L" if i % 2 else "R", lobe="parietal", vox_i=c[0], vox_j=c[1], vox_k=c[2],
                 length_mm=12, thickness_mm=1.5, morphology="linear_band", continuity="continuous", swi_appearance="hypointense_band", confidence_1to5="4")
        rows["R1"].append(dict(b, reader_id="R1", final_category="definite_cSS"))
        rows["R2"].append(dict(b, reader_id="R2", final_category="definite_cSS" if i < 5 else "non_cSS", noncss_type="" if i < 5 else "cortical_vein", confidence_1to5="3"))
    rows["R2"].append(dict(reader_id="R2", read_session="1", patient_id=r.case_code, lesion_id="99", hemisphere="R", vox_i=20, vox_j=20, vox_k=20,
                           final_category="probable_cSS", confidence_1to5="2", lobe="frontal", length_mm=4, morphology="dot_like"))
for rd, v in rows.items():
    cols = pd.read_csv(f"{W}/lesion_annotations_{rd}.csv").columns; pd.DataFrame(v).reindex(columns=cols).to_csv(f"{W}/lesion_annotations_{rd}.csv", index=False)
    pd.DataFrame([dict(reader_id=rd, patient_id=c, css_present_L="yes", css_present_R="yes" if rd == "R1" else "no", multifocality_L_0to2="2",
                       multifocality_R_0to2="1" if rd == "R1" else "0") for c in key.case_code]).to_csv(f"{W}/patient_annotations_{rd}.csv", index=False)
for bt in BATCHES:
    bd = f"{B}/reference_audit/batches/{bt}/review"; s = pd.read_csv(f"{bd}/annotation_sheet.csv")
    for rd in ("R1", "R2"):
        d = s.copy(); d["reader_id"] = rd; d["final_category"] = "non_cSS"; d["noncss_type"] = "other"; d["confidence_1to5"] = 4 if rd == "R1" else 3
        if rd == "R2": d.loc[0, ["final_category", "noncss_type"]] = ["probable_cSS", ""]
        d.to_csv(f"{bd}/annotations_{rd}.csv", index=False)
t = pd.read_csv(f"{W}/adjudication_TEMPLATE.csv", dtype=str).fillna("") if os.path.exists(f"{W}/adjudication_TEMPLATE.csv") else None
print("synthetic reads written")
