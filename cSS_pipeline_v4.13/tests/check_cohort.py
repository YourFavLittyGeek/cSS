"""v5.2.1 checks: cohort.py import (series choice) and compare_grades.py (patient-level agreement), known answers.
usage: check_cohort.py    (writes into $CSS_BASE/cohort_check/; no FreeSurfer, no DICOM: NIfTI + JSON sidecars)
1. import: in the SWI folder the processed SWI is chosen, never the minIP or the magnitude; the phase on the same grid
   goes to --phase, a phase on another grid does not; in the T1 folder the isotropic sagittal 3-D beats a thick axial
   MPR reformat; a missing FLAIR folder, a 3 mm SWI and a 3 mm-only T1 are flagged; --ids filters.
2. compare_grades: hand-computed exact agreement, within-1, unweighted / quadratic kappa, mean difference, presence
   sensitivity / specificity; a patient without a pipeline score is listed (not dropped); a total that is not L + R is
   flagged; out-of-range grades are refused; --template writes the ids."""
import os, sys, json, shutil, subprocess, numpy as np, nibabel as nib, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts"); sys.path.insert(0, S)
from css_common import cohen_kappa
py = sys.executable
B = f"{os.environ.get('CSS_BASE', '/tmp')}/cohort_check"; C = f"{B}/cohort"
def fail(m): print("FAIL:", m); sys.exit(1)
shutil.rmtree(B, ignore_errors=True)
def series(folder, name, vox, desc, image_type, shape=(20, 20, 10)):
    os.makedirs(folder, exist_ok=True); aff = np.diag(list(vox) + [1.0])
    nib.save(nib.Nifti1Image(np.ones(shape, np.float32), aff), f"{folder}/{name}.nii.gz")
    json.dump(dict(SeriesDescription=desc, ImageType=image_type, EchoTime=0.02), open(f"{folder}/{name}.json", "w"))
# M01: full set; M02: thick SWI, axial-only T1, no FLAIR, phase on another grid
series(f"{C}/M01/SWI", "10_SWI_Images", (0.9, 0.9, 1.5), "SWI_Images", ["ORIGINAL", "PRIMARY", "M", "SWI"])
series(f"{C}/M01/SWI", "11_mIP_Images_SW", (0.9, 0.9, 1.5), "mIP_Images(SW)", ["DERIVED", "PRIMARY", "MNIP"])
series(f"{C}/M01/SWI", "8_Mag_Images", (0.9, 0.9, 1.5), "Mag_Images", ["ORIGINAL", "PRIMARY", "M", "ND"])
series(f"{C}/M01/SWI", "9_Pha_Images", (0.9, 0.9, 1.5), "Pha_Images", ["ORIGINAL", "PRIMARY", "P", "ND"])
series(f"{C}/M01/t1", "3_AX_T1_MPR", (0.5, 0.5, 3.0), "AX T1 MPR", ["DERIVED", "SECONDARY", "MPR"])
series(f"{C}/M01/t1", "2_T1_MPRAGE_SAG", (1.0, 1.0, 1.0), "T1 MPRAGE SAG", ["ORIGINAL", "PRIMARY", "M"])
series(f"{C}/M01/Flair", "5_AX_FLAIR_MPR", (0.5, 0.5, 1.0), "AX FLAIR MPR", ["DERIVED", "SECONDARY", "MPR"])
series(f"{C}/M02/SWI", "4_SWI_Images", (0.9, 0.9, 3.0), "SWI_Images", ["ORIGINAL", "PRIMARY", "M", "SWI"])
series(f"{C}/M02/SWI", "5_Pha_Images", (0.9, 0.9, 3.0), "Pha_Images", ["ORIGINAL", "PRIMARY", "P"], shape=(20, 20, 5))
series(f"{C}/M02/T1", "3_AX_T1_MPR", (0.5, 0.5, 3.0), "AX T1 MPR", ["DERIVED", "SECONDARY", "MPR"])
series(f"{C}/M03/SWI", "4_SWI_Images", (0.9, 0.9, 1.5), "SWI_Images", ["ORIGINAL", "PRIMARY", "M", "SWI"])
env = dict(os.environ, CSS_BASE=B)
def run(*a, ok=True):
    r = subprocess.run([py, *a], capture_output=True, text=True, env=env)
    if ok and r.returncode: print(r.stdout[-1500:], r.stderr[-1500:]); fail("step failed: " + " ".join(a[:2]))
    return r
run(f"{S}/cohort.py", "import", C, "--ids", "M01,M02")
T = pd.read_csv(f"{B}/review/cohort_import.csv", dtype=str).fillna("").set_index("study_id")
if list(T.index) != ["M01", "M02"]: fail(f"--ids: {list(T.index)}")
m1, m2 = T.loc["M01"], T.loc["M02"]
if not m1.swi.endswith("10_SWI_Images.nii.gz") or m1.swi_kind != "swi" or "/raw/M01/SWI/" not in m1.swi: fail(f"M01 SWI choice {m1.swi}")
if not m1.phase.endswith("9_Pha_Images.nii.gz"): fail(f"M01 phase {m1.phase}")
if not m1.t1.endswith("2_T1_MPRAGE_SAG.nii.gz") or m1.t1_vox_mm != "1.00x1.00x1.00": fail(f"M01 T1 {m1.t1} {m1.t1_vox_mm}")
if not m1.flair.endswith("5_AX_FLAIR_MPR.nii.gz"): fail(f"M01 FLAIR {m1.flair}")
if m1["flags"] != "": fail(f"M01 flags {m1['flags']}")
f2 = set(m2["flags"].split(";"))
if not {"no_flair", "t1_not_3d", "swi_slice_gt_2mm", "phase_not_on_swi_grid", "no_phase"} <= f2 or m2.phase: fail(f"M02 flags {f2}, phase {m2.phase}")
print("1. import: SWI_Images chosen over mIP / Mag; Pha_Images on the SWI grid -> --phase; sagittal 1 mm iso T1 over the "
      f"3 mm axial MPR; M02 flagged {sorted(f2)}; --ids honoured")
# 1b. run: a stub run_css.sh records its arguments; M02 exits 3 (QC insufficient under strict QC)
os.makedirs(f"{B}/scripts", exist_ok=True)
open(f"{B}/scripts/run_css.sh", "w").write('echo "$@" > "$CSS_BASE/args_$1.txt"; [ "$1" = M02 ] && exit 3; '
                                           'mkdir -p "$CSS_BASE/review"; echo x > "$CSS_BASE/review/$1_manifest.json"; '
                                           'echo x > "$CSS_BASE/review/$1_candidates.csv"; exit 0\n')
shell = shutil.which("zsh")
if shell:
    run(f"{S}/cohort.py", "run")
    a1 = open(f"{B}/args_M01.txt").read().split()
    if a1[:2] != ["M01", m1.swi] or ["--t1", m1.t1] != a1[2:4] or "--recon" not in a1 or a1[a1.index("--phase") + 1] != m1.phase \
            or a1[a1.index("--flair") + 1] != m1.flair: fail(f"run_css arguments {a1}")
    a2 = open(f"{B}/args_M02.txt").read().split()
    if "--flair" in a2 or "--phase" in a2: fail(f"M02 arguments {a2}")
    R = pd.read_csv(f"{B}/review/cohort_run.csv").set_index("study_id")
    if R.loc["M01", "status"] != "ok" or R.loc["M02", "status"] != "qc_insufficient": fail(f"run statuses {R.status.to_dict()}")
    r2 = run(f"{S}/cohort.py", "run").stdout
    if "M01: already detected - skipped" not in r2: fail("re-run did not skip a detected study")
    print("1b. run: run_css.sh gets SWI, --t1 (sagittal), --flair, --recon, --phase; M02 without FLAIR / phase; exit 3 -> "
          "qc_insufficient; a detected study is skipped on re-run")
else:
    print("1b. run: skipped (zsh not installed)")

# 2. compare_grades on hand-made scores
os.makedirs(f"{B}/labels", exist_ok=True)
E = pd.DataFrame(dict(study_id=["M01", "M02", "M03", "M04", "M05", "M06"], expert_L=[0, 1, 2, 0, 1, 2],
                      expert_R=[0, 1, 2, 1, 0, 2], expert_total=[0, 2, 4, 1, 2, ""]))       # M05 total 2 != 1 + 0
E.to_csv(f"{B}/labels/expert_grades.csv", index=False)
Sc = pd.DataFrame(dict(subject=["M01", "M02", "M03", "M04", "M06"], L_score=[0, 1, 1, 0, 2], R_score=[1, 1, 2, 0, 2],
                       multifocality_0_4=[1, 2, 3, 0, 4], scoring_method="sulcal (Destrieux)", n_candidates=10,
                       n_unreviewed=[0, 0, 0, 3, 0]))
Sc.to_csv(f"{B}/review/css_scores.csv", index=False)
out = run(f"{S}/compare_grades.py", "--boot", "200").stdout
P = pd.read_csv(f"{B}/results/grade_comparison_patients.csv", dtype={"study_id": str}).set_index("study_id")
Sm = pd.read_csv(f"{B}/results/grade_comparison_summary.csv").set_index("scale")
if len(P) != 6 or "no pipeline score" not in P.loc["M05", "flags"] or "expert total != L + R" not in P.loc["M05", "flags"]:
    fail(f"M05 flags {P.loc['M05', 'flags'] if 'M05' in P.index else 'missing'}")
if "3 candidates unreviewed" not in P.loc["M04", "flags"]: fail("unreviewed flag")
a, b = np.array([0, 2, 4, 1, 4]), np.array([1, 2, 3, 0, 4])           # M01, M02, M03, M04, M06 totals
t = Sm.loc["total"]
want = dict(n=5, exact_agreement=0.4, within_1=1.0, mean_diff_pipeline_minus_expert=round(float((b - a).mean()), 3),
            kappa_quadratic=round(cohen_kappa(a, b, range(5), "quadratic"), 3), kappa_unweighted=round(cohen_kappa(a, b, range(5)), 3))
for k, v in want.items():
    if abs(float(t[k]) - v) > 1e-9: fail(f"total {k}: {t[k]} vs {v}")
pr = Sm.loc["cSS present (patient, total > 0)"]
if (int(pr.tp), int(pr.fn), int(pr.tn), int(pr.fp)) != (3, 1, 0, 1): fail(f"presence counts {pr.tp, pr.fn, pr.tn, pr.fp}")
hm = Sm.loc["cSS present (hemisphere, score > 0)"]
# hemispheres (expert>0, pipe>0): L M01 0/0 M02 1/1 M03 1/1 M04 0/0 M06 1/1; R M01 0/1 M02 1/1 M03 1/1 M04 1/0 M06 1/1
if (int(hm.tp), int(hm.fn), int(hm.tn), int(hm.fp)) != (6, 1, 2, 1): fail(f"hemisphere counts {hm.tp, hm.fn, hm.tn, hm.fp}")
Cf = pd.read_csv(f"{B}/results/grade_comparison_confusion_total.csv", index_col=0)
if int(Cf.values.sum()) != 5 or int(Cf.loc[4, "3"]) != 1: fail("confusion matrix")
print(f"2. compare_grades: total exact {t.exact_agreement:.0%}, within 1 {t.within_1:.0%}, quadratic kappa {t.kappa_quadratic}, "
      f"mean diff {t.mean_diff_pipeline_minus_expert:+.2f} (hand-computed); presence TP/FN/TN/FP 3/1/0/1, hemispheres 6/1/2/1; "
      "M05 without a score listed and its total flagged; M04 unreviewed flagged")
# 2b. the radiologist's own layout, as .xlsx when openpyxl is there (else .csv), and --results-only
json.dump(dict(field_T=1.5), open(f"{B}/review/M01_score.json", "w"))
rad = pd.DataFrame({"Patient name": ["M01", "M02", "M03", "M04", "M05", "M06"], "ID": ["T01", "T02", "T03", "T04", "T05", "T06"],
                    "R css": [0, 1, 2, 1, 0, 2], "l css": [0, 1, 2, 0, 1, 2], "cSS score (0-4)": [0, 2, 4, 1, 2, ""]})
try:
    import openpyxl  # noqa: F401
    rp = f"{B}/labels/radiologist.xlsx"; rad.to_excel(rp, index=False)
except ImportError:
    rp = f"{B}/labels/radiologist.csv"; rad.to_csv(rp, index=False)
run(f"{S}/compare_grades.py", "--expert", rp, "--boot", "50", "--out", f"{B}/results/rad")
Rr = pd.read_csv(f"{B}/results/rad_results.csv", dtype=str).fillna("").set_index("Patient name")
if list(Rr.columns[:4]) != ["ID", "R cSS", "L cSS", "cSS score (0-4)"]: fail(f"results columns {list(Rr.columns)}")
if (Rr.loc["M03", "ID"], Rr.loc["M03", "R cSS"], Rr.loc["M03", "L cSS"], Rr.loc["M03", "cSS score (0-4)"],
        Rr.loc["M03", "radiologist cSS score (0-4)"], Rr.loc["M03", "agree"]) != ("T03", "2", "1", "3", "4", "no"):
    fail(f"M03 row {Rr.loc['M03'].to_dict()}")
if Rr.loc["M02", "agree"] != "yes" or Rr.loc["M05", "cSS score (0-4)"] != "" or Rr.loc["M01", "field (T)"] != "1.5":
    fail(f"M02 / M05 / M01 rows {Rr.loc[['M01', 'M02', 'M05']].to_dict('records')}")
S2 = pd.read_csv(f"{B}/results/rad_summary.csv").set_index("scale")
if abs(float(S2.loc["total", "kappa_quadratic"]) - float(t.kappa_quadratic)) > 1e-9: fail("radiologist layout gives other statistics")
run(f"{S}/compare_grades.py", "--results-only")
Ro = pd.read_csv(f"{B}/results/css_results.csv", dtype=str).fillna("")
if list(Ro.columns[:5]) != ["Patient name", "ID", "R cSS", "L cSS", "cSS score (0-4)"] or len(Ro) != 5 or "radiologist R cSS" in Ro.columns:
    fail(f"--results-only {list(Ro.columns)} {len(Ro)}")
print(f"2b. radiologist's sheet as it is ({os.path.basename(rp)}: Patient name / ID / R css / l css / cSS score (0-4)) -> results "
      "sheet in that layout, pipeline + radiologist + agree, same statistics; --results-only writes the pipeline columns alone")
pd.DataFrame(dict(study_id=["M07"], expert_L=[3], expert_R=[0])).to_csv(f"{B}/labels/bad.csv", index=False)
if run(f"{S}/compare_grades.py", "--expert", f"{B}/labels/bad.csv", ok=False).returncode == 0: fail("out-of-range grade accepted")
os.remove(f"{B}/labels/expert_grades.csv"); run(f"{S}/compare_grades.py", "--template")
tp = pd.read_csv(f"{B}/labels/expert_grades.csv", dtype=str)
if tp.study_id.tolist() != ["M01", "M02"]: fail(f"template ids {tp.study_id.tolist()}")
print("   out-of-range grade refused; --template lists the imported ids")
print("RESULT cohort OK")
