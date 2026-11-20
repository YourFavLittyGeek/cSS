#!/usr/bin/env python3
"""Run the detector with chosen switches on COPIES of studies. Research software; expert review required.
usage: run_experiment.py M02,M03,...  --name NAME  [--flags CSS_V53=1,CSS_SOFT_GATES=1,CSS_3D_SEEDS=1]
The project is NOT touched. For every study the data/ and work/ files are copied (hard links where possible, so almost no disk) into
$CSS_BASE/experiments/NAME/{data,work,review}, detect_css.py runs there with the given environment switches, one study at a time
(about 2 GB of memory each; do not run two at once), and the outputs stay in experiments/NAME/review (+ work). Compare two such runs
with compare_pipelines.py. The special name "main" in compare_pipelines.py is the project itself.
Switches (all default OFF = current behaviour): CSS_V53 (the v5.3 rules E12-E25), CSS_SOFT_GATES (gate failures kept as last candidates),
CSS_3D_SEEDS (recorded-only 3-D plate seeds), CSS_USE_MIMIC, CSS_MIXED_REVIEW, CSS_SATO_LEGACY.
Writes experiments/NAME/EXPERIMENT.json (studies, switches, build id, time) and a detect log per study."""
import sys, os, glob, shutil, json, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base, build_id

a = sys.argv[1:]
if not a or a[0].startswith("-") or "--name" not in a: sys.exit(__doc__)
ids = [s for s in a[0].split(",") if s]; name = a[a.index("--name") + 1]
flags = dict(kv.split("=", 1) for kv in a[a.index("--flags") + 1].split(",") if "=" in kv) if "--flags" in a else {}
KNOWN = {"CSS_SLICE_GATE", "CSS_ALLOW_BAD_REG", "CSS_CONF", "CSS_CONF_GUARD", "CSS_CONF_ALLOW_OPTIMISTIC", "CSS_STRUCT", "CSS_V53", "CSS_SOFT_GATES", "CSS_3D_SEEDS", "CSS_E22_PIECES", "CSS_ZONE2", "CSS_ZONE2_FRAC", "CSS_SYLV_FRAC", "CSS_USE_MIMIC", "CSS_MIXED_REVIEW", "CSS_SATO_LEGACY", "CSS_KEEP_ALL", "CSS_RANK"}
bad = [k for k in flags if k not in KNOWN]
if bad: sys.exit(f"unknown switch(es) {bad}; known: {sorted(KNOWN)}")
if not name.replace("_", "").replace("-", "").isalnum() or name == "main": sys.exit("--name must be letters / digits / - / _ and not 'main'")
B = _base(); E = f"{B}/experiments/{name}"; S = os.path.dirname(os.path.abspath(__file__))
for d in ("data", "work", "review", "results"): os.makedirs(f"{E}/{d}", exist_ok=True)


def put(src, dst):
    if os.path.exists(dst): os.remove(dst)
    try: os.link(src, dst)
    except OSError: shutil.copy2(src, dst)


done, notes = [], []
for sid in ids:
    if not os.path.exists(f"{B}/data/{sid}_swi.nii") or not os.path.exists(f"{B}/work/{sid}_seg_swispace.nii.gz"):
        notes.append(f"{sid}: data/{sid}_swi.nii or work/{sid}_seg_swispace.nii.gz missing - skipped"); continue
    for sub in ("data", "work"):
        for f in glob.glob(f"{B}/{sub}/{sid}_*"):
            if os.path.isfile(f) and not any(x in f for x in ("_dropped", "_gen", "_3d_only", "_soft_gate", "_pial_sd", "_dark.nii")): put(f, f"{E}/{sub}/{os.path.basename(f)}")
    t0 = time.time(); env = dict(os.environ, CSS_BASE=E, **flags)
    r = subprocess.run([sys.executable, f"{S}/detect_css.py", sid], env=env, capture_output=True, text=True)
    open(f"{E}/review/{sid}_detect.log", "w").write(r.stdout + r.stderr)
    if r.returncode: notes.append(f"{sid}: detect exit {r.returncode} (see experiments/{name}/review/{sid}_detect.log)"); continue
    done.append(sid); print(f"{sid}: detected in {time.time() - t0:.0f} s with {flags or 'default switches'}", flush=True)
json.dump(dict(name=name, studies=done, switches=flags, build=build_id(), run_at=time.strftime("%Y-%m-%d %H:%M:%S"), notes=notes), open(f"{E}/EXPERIMENT.json", "w"), indent=1)
print("\n".join(notes)); print(f"experiment '{name}': {len(done)} studies in {E}\nnext: python {S}/compare_pipelines.py main {name} {','.join(ids)}")
