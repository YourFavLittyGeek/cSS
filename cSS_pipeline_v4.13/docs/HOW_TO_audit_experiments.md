# How to run the audit experiments (surface / soft gates / 3-D seeds) - research software; expert review required

All of these leave the project untouched: detections run on COPIES (hard links, almost no disk) in `~/css_project/experiments/<name>/`, one study at a time
(about 2 GB each, no other heavy job running). Switches are default OFF. Summaries are plain text; send them back.

## 0. One-time
```
conda activate css
cd ~/css_project
cp <unzipped>/docs/adjudication_M02-M11_v1.csv review/adjudication.csv      # your final decisions (replaces the individual reads in the reports)
```

## 1. F1 - is the mask-based pial distance a problem? (read-only; needs recon-all surface features)
```
python scripts/pial_compare.py M02,M03,M04,M05,M06,M07,M08,M09,M10,M11
open review/pial_compare_summary.txt
```
If `review/M0?_surface_features.csv` is missing for a study it says so (run `python scripts/surface_features.py M0X` first; recon-all cases only).
Look at the last lines: the AUC of mask vs mesh distance and the verdict.

## 2. F4 - soft generation gates
```
python scripts/run_experiment.py M02,M03,M04,M05,M06 --name base   --flags CSS_V53=1
python scripts/run_experiment.py M02,M03,M04,M05,M06 --name soft   --flags CSS_V53=1,CSS_SOFT_GATES=1
python scripts/compare_pipelines.py base soft M02,M03,M04,M05,M06
open review/compare_pipelines_base_vs_soft_summary.txt
```
"gate-dropped in A, shown in B" = the objects the mode would add to the reading list, by gate. Also read `experiments/soft/work/M0?_soft_gate.csv`.
No called cSS may be LOST. Expect many extra objects (the phantom: 4 -> 34): that is the workload cost.

## 3. F2 - 3-D plate seeds (recorded only)
```
python scripts/run_experiment.py M02,M03,M04,M05,M06 --name seeds3d --flags CSS_V53=1,CSS_3D_SEEDS=1
python scripts/compare_pipelines.py base seeds3d M02,M03,M04,M05,M06
python - <<'PY'
import json, glob
for p in sorted(glob.glob("experiments/seeds3d/review/M0*_manifest.json")):
    print(p.split("/")[-1][:3], json.load(open(p))["detect"]["parameters"]["seeds3d"])
PY
```
The candidates must be unchanged (compare_pipelines: all "same"). The manifest lines give, per study, how many 3-D objects exist, how much of the 2-D object
volume the 3-D path covers, and how many 3-D objects have no 2-D counterpart (`experiments/seeds3d/work/M0?_3d_only.csv`: centroid, hemisphere, nearest cortex label,
plate-ness, sheet angle). Open a few of those centroids in the reviewer or freeview to see whether they are cSS the 2-D path misses.

## 4. Orientation of your cSS (read-only)
`python scripts/shape_probe.py ...` (see HOW_TO_RUN_v5.7-D.md) lists axis_angle_deg of every object next to your calls: how many cSS lie out of the axial plane.

## 5. Any other switch combination
`run_experiment.py IDS --name X --flags CSS_V53=1,CSS_USE_MIMIC=1` ... then `compare_pipelines.py main X IDS` ("main" = the project itself).
`rm -rf ~/css_project/experiments/<name>` removes an experiment (hard links: no other file is affected).
