# P2_REPORT.md - Stage 2 P2: candidate patches, schema css-patch/2.0 (SYNTHETIC data only), 2026-11-20

Research software. No clinical file was opened. The Stage 1 engine, `scripts/` (incl. `surface_aligned_patch.py`) and
`unified_score/` are unchanged; the production extractor is executed, never copied or edited.

## What was built
`unified_engine/uengine/imaging/patches.py` - `extract_study(base, sid, write)`:
1. runs the P1 index first (non-synthetic data refused before any file is opened); uses ONLY channels with status ok /
   low_confidence; a study that fails the geometry gate, or has no usable `pial_sd` (surface frame), gets every object skipped with
   the reason;
2. **surface patch (css-patch/1.0)** from `scripts/surface_aligned_patch.extract_patch`, pinned sha256 `ff18972a...`, called with the
   same inputs as its own CLI (brain = filled SWI > 0, labels for the tissue-side check). Missing channels get an all-False `valid_<ch>`,
   as in 1.0;
3. **native 2.5D stack (new)**: the object's acquired axial slices (centre +- 2), sampled ON each slice plane (slice index exact, no
   through-plane interpolation), in-plane 0.5 mm over 32 x 32 mm (5 x 65 x 65); axes made storage-independent (toward R, toward A,
   inferior -> superior); validity per channel as in 1.0 (inside image and brain);
4. object masks on both grids; metadata: per-channel image sha256, pial_sd sha256, affine hash, frame hash, patch hash (all arrays),
   P1 index hash, registration and channel status, extractor sha256, versions, `synthetic: true`;
5. `write=True` -> `$base/unified_engine/patches/ID/<list>_<id>.npz` + `manifest.csv` only (never `review/`, which the 1.0 CLI uses).
   `load_patch()` refuses a patch whose arrays no longer match its hash.

Synthetic generator extended: candidate objects defined in world coordinates - two subpial cSS-like SHEETS (~7 mm across, 1.3 mm
deep), surface veins as TUBES just outside the pial surface, a transcortical vein crossing the cortex, a 2-voxel speck - darkened on
the SWI; label maps and detector-like tables (id + fingerprint only); truth written separately (`unified_engine/image_truth/`), never
read by the extractor. CLI: `run_imaging.py patches SID --base DIR [--write]`.

## Tests (`tests/test_imaging_patches.py`, 12; all imaging tests 49 / 49; full runner 0 failing stages, Stage 1 119 / 119 + 35 / 35)
- **fidelity**: every css-patch/1.0 array is BIT-IDENTICAL to the production CLI's output on the same synthetic study (90 arrays,
  6 patches; dtype, shape, bytes) and the 1.0 metadata fields agree; a changed extractor hash is refused.
- **content**: the speck is skipped with the extractor's own reason; object keys; sheet below the pial surface vs tube in the CSF
  (signed distance at the centre); the sheet is >= 2x wider across the surface than any surface vein and wider across than deep; the
  transcortical vein extends along n.
- **native stack**: axes toward R / A, slices inferior -> superior at the acquired 1.2 mm spacing, the object on the centre slice; every
  value equals a pure 2-D interpolation of its OWN slice (no through-plane contribution, 1e-6); slices beyond the array are invalid.
- **invariance**: the same study stored RAS / LPS / RPI gives the same frames, surface patches, native stacks and object masks (1e-4).
- **refusals / provenance**: a misregistered FLAIR is absent from every array and recorded as `missing_channels: misregistered`;
  refused geometry and a missing pial_sd block every object (only the manifest is written); non-synthetic base / code refused with
  the folder unchanged; only `unified_engine/patches/SYN01/` written; reproducible patch hashes; an edited patch is refused; the
  manifest carries no truth.

Exit criterion (roadmap): 1.0 patches bit-identical - met; 2.0 additions tested - met.

## Findings
1. The production extractor caches arrays by Python object id (`_ARR`) and never clears it; `extract_study` clears it after each study
   (memory only; no wrong values, since the cache keeps the image alive).
2. The first synthetic "cSS band" was 2.7 mm wide, i.e. not a sheet; caught by the sheet-vs-tube test and widened to ~7 mm. The
   generator's geometry is a design choice, not a measured property of cSS.
3. Storing native slice centres rounded to 1e-4 mm moved samples off the acquired plane by ~2e-6 voxel; now stored unrounded.

## Next: P3
Parametric synthetic generator with acquisition variability (voxel size, noise, bias field, blooming by TE, vendor phase sign), mimic
subtypes, reader label noise, indeterminate and insufficient-quality cases; re-check of the provisional P1 thresholds on it.
