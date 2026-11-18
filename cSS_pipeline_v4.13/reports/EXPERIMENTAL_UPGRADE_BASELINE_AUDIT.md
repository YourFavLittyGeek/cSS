# Experimental upgrade — Stage 0 baseline audit

Date 2026-11-18. Branch `experimental/structural-css-detection`, started from `115721f` (v5.11.0-phase1).
**Nothing under `scripts/` was changed.** Every number below comes from one of three sources, each named in its own section:
- **(a)** result tables the user produced on the Mac (`v510_compare.csv`, `confidence_fit.csv`, `radiologist_grades.csv`, M12–M15 lists);
- **(b)** the production code, read here;
- **(c)** phantom runs of the unmodified production detector in this sandbox.

No patient image is available here. Scripts are in `experimental/stage0/`, and outputs in `/home/user/cSS_structural_upgrade/stage0/`.

## 0.1 Object counts: 111 vs 141 (and 118 / 147)

These are four different object sets, and none of them is wrong:

| Set | Objects | How it is built | Label |
|---|---|---|---|
| `v510_compare.csv` | 147 | Every object of the M02–M11 lists the v5.10 acceptance test started from | Primary reader's shared call, matched by fingerprint |
| … shown in the v5.10 copy run | 118 | 147 minus the 29 that E30 (24.2 % confidence cut) excluded in that copy | Same |
| **Previous audit `feature_table.csv`** | **111** | 118 shown, restricted to objects with a usable label | Primary reader: 47 cSS / 29 Normal / 14 Vessel / 14 Artifact / 1 Near ICH. A cSS call on a radiologist-zero side (4) and unread zero-side objects (2) were counted as negatives. |
| **`confidence_fit.csv`** (fit_confidence.py) | **141** | 147 objects of the full lists (before any cut), minus 6 with no read at all | cSS if **any** read (ST, ML, Redo_v53, Blind_v57 + adjudication) said cSS; radiologist-zero side → 0. Result: 54 cSS / 87 not. |

- **Join on (study, object id)**: 141 matched, 6 only in `v510_compare` (unread), 0 unmatched in the other direction.
- **Status disagreements**: 7 objects are cSS under the any-read rule but not under the primary-reader rule:
  - M04 #11, #14, #19;
  - M06 #5, #11, #12;
  - M11 #12.
- **Consequence**:
  - "54 cSS" and "47 cSS" describe the same objects with different label rules.
  - The confidence model was fitted on the any-read label.
  - The feature audits used the primary reader.
  - Neither label is expert lesion-level ground truth.

**Table**: `stage0/reconciliation_111_vs_141.csv`.

## 0.2 tube_ratio AUC — direction made explicit

AUC here means P(score of a cSS object > score of a comparison object), with ties counted as ½. The positive class is the cSS call. Confidence intervals come from a patient-cluster bootstrap (2,000 resamples).

| Comparison | n cSS / other | AUC (raw) | 1 − AUC | 95 % CI (raw) |
|---|---|---|---|---|
| Shown objects, cSS vs Vessel calls on radiologist-positive sides | 47 / 11 | 0.135 | 0.865 | 0.02–0.30 |
| Shown objects, cSS vs Vessel calls on any side (previous audit's 0.83) | 47 / 14 | 0.174 | 0.826 | 0.04–0.36 |
| All 147, cSS vs Vessel calls | 47 / 20 | 0.149 | 0.851 | 0.05–0.29 |
| Previous audit set, cSS vs all labelled non-cSS | 47 / 64 | 0.324 | 0.676 | 0.21–0.49 |
| Held-out M12–M15 (ST blind read), cSS vs Vessel | 19 / 10 | 0.403 | 0.597 | 0.00–0.83 (oriented) |

The raw AUC is **below 0.5**: lower tube_ratio goes with cSS calls, as the feature's definition intends. The earlier "0.83" was 1 − AUC, reported as an oriented value. It is a correct number with an implicit direction, not an error.

The separation is weakest against non-vessel mimics (0.68), and it did not replicate on the held-out read.

## 0.3 Hessian implementation — verified, with one definitional issue

These lines of `detect_css.py` were checked against an independent re-implementation (`structural_detection/common.py`):

| Lines | What they do |
|---|---|
| 510–533 | Hessian computation and eigenvalue selection |
| 529 | Per-voxel `tube_ratio` |
| 911 | Object-level median |

- **Identical maths.** Same σ in mm converted per axis, derivatives divided by voxel sizes, σ² normalisation, eigenvalues sorted by |λ|, best scale = largest positive λ3. Maximum per-voxel difference on four synthetic shapes was 2.4 × 10⁻⁷ (float32 rounding).
- **Sign is correct.** λ3 > 0 is an intensity minimum, i.e. a dark structure on SWI.
- **Issue: `|λ2|`.**
  - Production uses |λ2|/λ3. A voxel whose second curvature is negative (a saddle: intensity rises along that axis) counts as tube-like.
  - The corrected variant max(λ2, 0)/λ3 was computed next to it. The production value is not replaced.
  - Synthetic shapes, voxels inside the structure: no effect on plate, tube or blob (identical medians). Thick plate: 0.284 vs 0.268.
  - Synthetic shapes, the 2-voxel shell around a plate: 42 % of the dark voxels are saddles, and the median rises from 0.06 (signed) to 0.33 (production).
  - **Production objects on phantoms (PH3, PH6; `figures/fig2`).**
    - Phantom cSS lesions: saddle fraction 0.04–0.36, which inflates tube_ratio by +0.03 to +0.26.
    - Sulcal-CSF vein objects: saddle fraction 0.46–0.68. Their production tube_ratio of ~0.52 comes **entirely** from saddle voxels; the signed value is 0.00.
    - In these phantoms, then, the production feature separates veins *because of* the |λ2| choice. The signed variant alone would make those veins look sheet-like.
  - **Conclusion.** The issue is real and material, but "fixing" it is not simply better. Keep both values. The saddle fraction is its own informative quantity on phantoms. Whether either helps on patients is untested, because no images are available here.
- **Other properties, unchanged and documented:**
  - Only 2 scales (0.8 / 1.6 mm).
  - On 3 mm slices, σ 0.8 mm is 0.27 voxel through-plane.
  - The median over the object discards heterogeneity.

## 0.4 Versions

| Item | Value | Problem |
|---|---|---|
| `scripts/VERSION` | v5.11.0-phase1 | — |
| `RULESET` in detect_css.py (l. 84) → `rule_version` column; manifest `pipeline_version` | "v4.18" | Stale: every list written by v5.x says v4.18 (confirmed in the M12–M15 manifests and candidates) |
| `scripts/BUILD` | "833e631… 2026-11-03" | `export-subst` only fills it in `git archive` exports. 833e631 is not a commit in this repository, so the file is a stale copy and identifies nothing. |
| `confidence_model.json` (r_74) | no `cut_method` key | Fitted before Phase 1. Under v5.11.0 E30 refuses it unless `CSS_CONF_ALLOW_OPTIMISTIC=1`, so results made with it are not reproducible on the current code without that override. |
| Feature schema | css-features/1.0, manifest css-manifest/1.0 | Consistent |

**Recommendation** (not done here, because it changes production output text): stamp `VERSION` into `rule_version`/`pipeline_version`, or add a `detector_version` column next to the existing ones.

## 0.5 Volume gate G1 (25 mm³) — impact on phantoms, read-only

`stage0/volume_gate_sweep.py` inserted 36 subpial cSS-like lesions into copies of PH3, using 12 designs × 3 sites. It then ran the **unmodified** detector (`CSS_V53=1 CSS_ZONE2=1`) and traced every lesion to its fate.

The designs were:
- discs of radius 1.5–6 mm;
- strips 1 or 2 slices high, 8 or 14 mm long;
- a fragmented disc.

| Run | Shown | Dropped by generation gates | Excluded by rules | Not generated |
|---|---|---|---|---|
| Sites ≥ 12 mm from the midline | 33 / 36 | 3 (G1: true volume 6–8 mm³, measured 18–21 mm³) | 0 | 0 |
| Sites anywhere | 23 / 36 | 8 (G1 ×5: true 5–11 mm³; **G3 elongation ×3: true 18, 95 and 99 mm³ discs**) | 5 (all E13 midline) | 0 |

- **G1 acts on the measured component, not on the lesion.** Blooming and the ridge mask inflate small lesions about 2–3×, so true lesions down to ~9 mm³ survive and ≤ 8 mm³ are lost. The 25 mm³ figure is not the size of the smallest detectable lesion.
- **G3 (elongation ≥ 2) dropped compact disc-shaped patches of up to ~100 mm³.** A convexity cSS patch seen roughly en face can be round. This is a larger sensitivity risk than G1 on these phantoms. Soft gates (`CSS_SOFT_GATES=1`, already in production, default off) would keep such objects as tier 4.
- 1-slice strips were shown, because blooming spreads them over ≥ 2 slices.
- **Limitations**:
  - Phantom intensity model, a single host, and 3 sites per design.
  - This says nothing about how often real cSS is this small.
  - No threshold was changed.

Outputs: `stage0/volume_gate*/volume_gate_sweep.csv`, `figures/fig3_*`.

## 0.6 Surface width (`surf_width_mm`) — phantom reassessment

The v4.19 PH6 result (cSS 5–7.6 mm vs vein 0.5–0.9 mm) was built into the phantom:
- the phantom cSS are wide patches;
- the veins are sampled 0.8 mm tubes outside the surface.

Its own resolution test already showed that a band 1–2 slices high measures like a vein.

The voxel-based analogue (`sc_width_mm`, module B) was re-measured on bands 1, 2, 4 and 8 slices high (1.2 mm slices). Width follows the band height (`figures/fig5`, `test_results/phantom_tests.json`). On real data the earlier feature validation found surface width mostly reflects size (ρ 0.50–0.80) and it was available only for M12–M15.

**Verdict.** It is a resolution- and size-limited measure. It is not a shape discriminator unless conditioned on size and slice coverage, and it is never an exclusion criterion.

## 0.7 Baseline tests established

- Production phantom outputs were hashed before any experimental code existed (`test_results/baseline_production_hashes.txt`).
- `experimental/run_all_checks.sh` rebuilds PH3/PH6, runs the unmodified detector, and checks three things:
  1. the hashes are byte-identical (they were);
  2. the PH3 list is identical with every experimental flag set to 1, because production never reads those flags;
  3. no file under `scripts/` references the experimental package.
