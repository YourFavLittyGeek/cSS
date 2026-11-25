# Processing methods: requirements, order and retry (2026-11-25)

Implemented in `cSS_pipeline_v4.13/app/pathway_rules.py` (pure functions, tests in `tests/test_pathway_rules.py`).
There is no "SynthReg" anywhere in the code or in FreeSurfer 8.2.0 on the user's Mac; the learned registration used is
`mri_synthmorph` (SynthMorph). Its model files `synthmorph.{rigid.1,affine.2,deform.3}.h5` are installed in
`/Applications/freesurfer/8.2.0/models`, and `recon-all -no-v8` exists in 8.2.0 (checked on the Mac).

| Method | What runs | Needs | Not used when |
|---|---|---|---|
| SynthSeg (`synthseg`) | `mri_synthseg --parc --robust` on the T1, `mri_coreg` SWI→T1 | any T1 | no T1 |
| Fast re-registration (`coreg_masked`) | same labels, T1 masked by them, `mri_coreg` | any T1 | no T1 |
| SynthMorph (`synthmorph`) | `mri_synthmorph register -m rigid` | T1, `mri_synthmorph` + rigid model, whole-brain SWI | partial-slab SWI (< 90 mm along the slices), tool/model missing |
| recon-all (`recon`) | `recon-all -all -no-v8`, `bbregister --t2 --init-coreg` | 3-D T1, every voxel side ≤ 1.3 mm, ~2-3 h | thick-slice / 2-D / reformatted T1, tools missing |
| SWI-only (`swi_only`) | SynthSeg on the SWI | SWI | — (partial slab works, flagged low confidence) |

Order: SynthSeg → Fast re-registration → SynthMorph → recon-all → SWI-only, skipping methods already tried or not
suitable. If two T1 methods both miss the 1.5 mm alignment check by more than 2 mm, the T1 is probably from another
session (or the patient moved): SWI-only is recommended instead of more T1 methods (the user's project had seven studies
with shifts of 1.8-4.3 mm that kept being retried with T1 methods). Automatic retries stay limited to the fast methods
(Fast re-registration, SynthMorph); recon-all and SWI-only are recommended and need one click.

Every list of methods in the app shows ✓ worked · ✗ tried and failed (reason) · ○ not tried yet · 🚫 not suitable (why,
disabled). Every method failure is recorded in `patients.json` `tried` (pathway, shift or reason, step, time); setup
problems (licence, FreeSurfer, disk, dcm2niix), the import step and "stopped by you" are not counted against a method.

Also fixed: `prep_anat.sh` re-used a finished recon-all (bbregister) even when another registration method had been chosen,
so a retry silently repeated the same result; `cohort.py` chose a 1-slice localizer split off by dcm2niix as the SWI
(Study-026) because it had the smallest voxels.

## Sources
- recon-all needs a T1 with voxels below ~1.3 mm: B. Fischl, FreeSurfer list, https://www.mail-archive.com/freesurfer@nmr.mgh.harvard.edu/msg29737.html
- recon-all-clinical (any contrast / resolution, thickness degrades with spacing): https://surfer.nmr.mgh.harvard.edu/fswiki/recon-all-clinical
- FreeSurfer 8 stream (SynthStrip / SynthSeg / SynthMorph inside recon-all, ~24-80 GB): https://surfer.nmr.mgh.harvard.edu/fswiki/ReleaseNotes, https://surfer.nmr.mgh.harvard.edu/fswiki/rel7downloads/rel8notes
- SynthSeg (any contrast, up to 10 mm spacing, `--robust`, `--threads`, `--crop`): https://surfer.nmr.mgh.harvard.edu/fswiki/SynthSeg, https://github.com/BBillot/SynthSeg
- SynthStrip memory (resampling to 1 mm; one instance at a time): https://github.com/freesurfer/freesurfer/issues/1032, https://github.com/nipreps/mriqc/issues/1437
- mri_synthmorph (`register -m rigid|affine|deform|joint`, resamples to 1 mm, models in `$FREESURFER_HOME/models`): https://github.com/freesurfer/freesurfer/blob/dev/mri_synthmorph/mri_synthmorph, https://martinos.org/malte/synthmorph/
- mri_coreg (two images only, `--threads`, masks): https://surfer.nmr.mgh.harvard.edu/fswiki/mri_coreg
- bbregister (needs recon-all surfaces, `--t2` for T2*-like contrast, partial FOV needs `--int`): https://surfer.nmr.mgh.harvard.edu/fswiki/bbregister
