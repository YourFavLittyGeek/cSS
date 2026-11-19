"""uscore_synthbase.py - writes a SYNTHETIC test base (SYN01..SYNnn) laid out like a production $CSS_BASE, for the end-to-end
pipeline tests only. Each study = 4 adversarial scenes stacked along x (one candidate each). IDs never start with M (no
collision with real patients); the manifest marks them synthetic. Never use these for model development or validation."""
import os, csv, json
import numpy as np
import uscore_synth as sy

KINDS = [("css_convexity", "cSS"), ("css_sulcal_bank", "cSS"), ("surface_vein", "Vessel"), ("skull_interface_artifact", "Artifact"),
         ("thin_curved_css", "cSS"), ("vein_parallel_to_sulcus", "Vessel"), ("extracranial_artifact", "Artifact"), ("fragmented_css", "cSS")]


def write_base(B, n_dev=6, n_ho=3, seed=5000):
    import nibabel as nib
    for d in ("review", "data", "work"): os.makedirs(f"{B}/{d}", exist_ok=True)
    S = sy.scenes(); man = []
    for si in range(n_dev + n_ho):
        sid = f"SYN{si + 1:02d}"; role = "development" if si < n_dev else "held-out"
        picks = [KINDS[(si + j) % len(KINDS)] for j in range(4)]
        blocks = [sy.build(n, S[n], seed + 10 * si + j) for j, (n, _) in enumerate(picks)]
        cat = lambda k: np.concatenate([b[k] if b[k] is not None else np.zeros(sy.SHAPE, bool) for b in blocks], 0)
        img, raw, ves, psd = cat("img"), cat("raw"), cat("ves"), np.concatenate([b["psd"] for b in blocks], 0)
        lab = np.zeros(img.shape, np.int16); rows = []; calls = []
        for j, b in enumerate(blocks):
            m = np.zeros(img.shape, bool); m[j * sy.SHAPE[0]:(j + 1) * sy.SHAPE[0]] = b["cand"]; lab[m] = j + 1
            P = np.argwhere(m).mean(0); vol = float(m.sum() * np.prod(sy.VOX))
            rows.append(dict(cand_id=j + 1, vox_i=P[0], vox_j=P[1], vox_k=P[2], volume_mm3=vol, infra_frac=0.0, infratentorial=0,
                             near_ich_suggest=0, region="synthetic", confidence_pct=""))
            calls.append(dict(cand_id=j + 1, call=picks[j][1], vox_i=P[0], vox_j=P[1], vox_k=P[2], volume_mm3=vol))
        A = np.diag(list(sy.VOX) + [1.0])
        nib.save(nib.Nifti1Image(lab, A), f"{B}/review/{sid}_candidates.nii.gz")
        nib.save(nib.Nifti1Image(img, A), f"{B}/data/{sid}_swi.nii")
        nib.save(nib.Nifti1Image(ves.astype(np.uint8), A), f"{B}/work/{sid}_vessels.nii.gz")
        nib.save(nib.Nifti1Image(psd.astype(np.float32), A), f"{B}/work/{sid}_pial_sd.nii.gz")
        os.makedirs(f"{B}/raw/{sid}/SWI", exist_ok=True); nib.save(nib.Nifti1Image(raw, A), f"{B}/raw/{sid}/SWI/swi.nii.gz")
        for name, rr in ((f"{sid}_candidates.csv", rows), (f"{sid}_calls.csv", calls)):
            with open(f"{B}/review/{name}", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rr[0])); w.writeheader(); w.writerows(rr)
        json.dump(dict(anatomy="T1 (synthetic)", label_shift_mm=0.1, registration_ok=True, voxel_mm=list(map(float, sy.VOX))),
                  open(f"{B}/review/{sid}_qc.json", "w"))
        man.append(dict(study_id=sid, starts_with_M="no", decision="include", role=role, exclusion_reason="", scoreability="synthetic",
                        source="synthetic test base", note="SYNTHETIC TEST ONLY"))
    man.append(dict(study_id="M02", starts_with_M="yes", decision="exclude", role="excluded", exclusion_reason="real patient: not part of a synthetic test",
                    scoreability="", source="", note=""))
    with open(f"{B}/manifest_synthetic.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(man[0])); w.writeheader(); w.writerows(man)
    return f"{B}/manifest_synthetic.csv"
