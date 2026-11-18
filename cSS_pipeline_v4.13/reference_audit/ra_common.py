"""Shared helpers for the reference-standard audit tools (read-only on production; never imported by scripts/)."""
import os, re, hashlib, numpy as np, pandas as pd

B = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project"))
OUT = os.path.join(B, "reference_audit")
STAGE_CODE = {"shown": 1, "excluded": 2, "dropped": 3}          # label value in ID_audit_objects.nii.gz = code*100000 + id

def uid(sid, stage, oid):
    return f"{sid}-{stage[0].upper()}{int(oid):04d}"

def label_value(stage, oid):
    return STAGE_CODE[stage] * 100000 + int(oid)

# exclusion mechanism from the production reason text / gate id (categories only; the exact reason is kept verbatim)
CATS = [("confidence threshold", r"low confidence"), ("volume gate", r"G1_volume|volume <|fewer than 5 voxels|G0_tiny"),
        ("slice gate", r"G2_slices|slices"), ("elongation gate", r"G3_elongation|elongation"), ("no cortex gate", r"G4|no cortex"),
        ("skull / skull-base position", r"skull|skull base|skull-base|lowest 20|orbitofrontal"),
        ("infratentorial / basal position", r"infratentorial|tentorial|basal cistern|cerebell|brainstem"),
        ("midline / fissure position", r"midline|interhemispheric|Sylvian|fissure"),
        ("outside cortex / CSF position", r"outside the cortex|off the cortex|ventric"),
        ("vessel / vein shape", r"vein|vessel|tubular|tube"), ("size / extent", r"extent|larger than"),
        ("contrast / artifact", r"ill-defined|edge contrast|artifact|darker than|speck|microbleed")]
def category(reason):
    r = str(reason)
    for c, pat in CATS:
        if re.search(pat, r, re.I): return c
    return "other"

SIZE_BINS = [0, 25, 50, 100, 250, 1000, np.inf]
SIZE_LBL = ["<25", "25-50", "50-100", "100-250", "250-1000", ">=1000"]
def size_bin(v):
    return pd.cut(pd.Series(v, dtype=float), SIZE_BINS, labels=SIZE_LBL, right=False).astype(str).to_numpy()

# Desikan-Killiany (aparc) cortical label -> lobe; the label number is aparc's 1000/2000 + index
DK = {1: "bankssts", 2: "caudalanteriorcingulate", 3: "caudalmiddlefrontal", 5: "cuneus", 6: "entorhinal", 7: "fusiform", 8: "inferiorparietal",
      9: "inferiortemporal", 10: "isthmuscingulate", 11: "lateraloccipital", 12: "lateralorbitofrontal", 13: "lingual", 14: "medialorbitofrontal",
      15: "middletemporal", 16: "parahippocampal", 17: "paracentral", 18: "parsopercularis", 19: "parsorbitalis", 20: "parstriangularis",
      21: "pericalcarine", 22: "postcentral", 23: "posteriorcingulate", 24: "precentral", 25: "precuneus", 26: "rostralanteriorcingulate",
      27: "rostralmiddlefrontal", 28: "superiorfrontal", 29: "superiorparietal", 30: "superiortemporal", 31: "supramarginal", 32: "frontalpole",
      33: "temporalpole", 34: "transversetemporal", 35: "insula"}
LOBE = {"frontal": [3, 12, 14, 17, 18, 19, 20, 24, 27, 28, 32], "parietal": [8, 22, 25, 29, 31], "temporal": [1, 6, 7, 9, 15, 16, 30, 33, 34],
        "occipital": [5, 11, 13, 21], "cingulate": [2, 10, 23, 26], "insula": [35]}
LOBE_OF = {k: lobe for lobe, ks in LOBE.items() for k in ks}
def region_lobe(label):
    try: l = int(label)
    except (TypeError, ValueError): return "", ""
    if 1000 <= l < 3000:
        k = l % 1000; return DK.get(k, f"label{l}"), LOBE_OF.get(k, "other")
    return f"label{l}", "non-cortical"

def nearest_cortex_label(seg, vox_ijk, max_mm=10.0, vox=(1, 1, 1)):
    i, j, k = [int(x) for x in vox_ijk]; r = [int(np.ceil(max_mm / v)) for v in vox]
    sl = tuple(slice(max(c - rr, 0), c + rr + 1) for c, rr in zip((i, j, k), r)); sub = seg[sl]
    idx = np.argwhere((sub >= 1000) & (sub < 3000))
    if not len(idx): return 0
    c0 = np.array([s.start for s in sl]); d = (((idx + c0 - [i, j, k]) * np.asarray(vox)) ** 2).sum(1)
    return int(sub[tuple(idx[d.argmin()])])

def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else ""
