# Production false-negative analysis — what is known now, and the plan to measure it

## What is known today (from existing files only; no new annotation)
1. **No valid sensitivity estimate exists.** All cSS labels were given to objects production showed; the "100 %" in earlier tables is
   produced by that selection.
2. **Misses are documented already** (reader-drawn marks during candidate review, `reader_missed_marks.csv`; 10 unique marks):
   | Mark | Production fate (production's own trace) | Failure type |
   |---|---|---|
   | M06 #3 | not generated (outside search zone / not dark enough / no ridge) | 1 never generated |
   | M06 #5 | not generated | 1 never generated |
   | M06 #4 | below a generation gate (size / slices / shape) | 2 generated, removed (gate) |
   | M14 #1 | excluded object 23 "off the cortex: lies in the sulcal CSF without touching the cortex" | 2 generated, removed (rule) |
   | M06 #1 | overlaps shown #7, but also excluded skull-band objects 12 / 16 and a gate drop | partial: lesion split, part removed |
   | 6 others | overlap shown candidates | extent beyond the candidate, not a miss |
   These were noticed incidentally, by 2 readers, mostly in M06; they are a floor.
3. **Mechanism-specific risks seen on phantoms (Stage 0)**: G1 volume gate removes lesions <= ~8 mm3 true volume (blooming makes the
   measured object 2-3x larger); G3 elongation dropped compact disc-shaped patches up to ~100 mm3; midline rules removed 5 / 36 inserted
   lesions placed near the midline. Phantoms show possibility, not frequency.
4. **Excluded objects were audited unblinded** (M02-M06, 129 read; viewer displayed the rule) and none was called cSS. Because the
   reader saw the rule, this cannot be used as an estimate (anchoring); 0 / 129 would otherwise bound the rate at <= 2.3 %.
5. **Size of the rejected pool** (current lists, 14 studies): 800 rule-excluded objects - skull / skull-base position 432,
   infratentorial / basal 142, midline / fissure 70, contrast / artifact 51, confidence cut 44, vessel / vein 37, size / extent 18,
   outside cortex 6 - plus generation-gate drops (hundreds per study; counted by `inventory.py` on the Mac).

## How the true false negatives will be measured
Three failure types, each measured by the matching pathway:
| Type | Definition | Measured by |
|---|---|---|
| 1 never generated | expert lesion with no production object within 3 mm | pathway A (whole scan) - the only source |
| 2 generated, then removed | expert lesion that matches a rule-excluded object (by mechanism) or a generation-gate drop (by gate) | pathway A (which mechanism removed real lesions) + pathway B (how often each mechanism removes cSS, design-based) |
| 3 retained, mis-ranked / mis-read | expert lesion on the shown list but low in rank, or called non-cSS by the original reader | pathway A matched to rank (`evaluate.py: rank`) and to the original reads |

Estimators (`reference_audit/evaluate.py`):
- lesion-level sensitivity = expert lesions retained on the shown list / all expert lesions (definite; definite + probable), patient-
  cluster bootstrap CI; FN per scan; breakdown by length, morphology, lobe, confidence, fate / mechanism.
- patient-side sensitivity (>= 1 expert lesion retained in a positive hemisphere) and specificity (no shown object on an expert-negative
  side); object-level PPV of shown objects and FP per scan (a shown object matching no expert cSS lesion).
- rejected-object cSS rate per stratum p_h = cSS / reviewed (exact Clopper-Pearson CI); estimated cSS objects in the pool
  T = sum N_h p_h (stratified SRS, batches pooled per stratum, N_h from the inventory). **Primary interval: conservative** =
  N-weighted sum of the stratum exact limits. The stratified normal-approximation interval is also reported but is NOT used: in a
  4,000-run simulation on the real stratum sizes (`reference_audit/tests/sim_estimator.py`) the estimator was unbiased (|bias| <= 0.0005)
  but the normal interval covered the true rate only 60-65 % of the time at true rates of 1-3 % (91 % at 10 %); the conservative
  interval covered it in 100 % (it is wide). 0 cSS in 30 reviewed objects of a mechanism -> exact one-sided 95 % upper bound
  1 - 0.05^(1/30) = 9.5 %.
- inference is design-based about the rejected objects of these 14 scans (valid whatever the correlation within patients); a rate for
  new patients needs more patients. Strata that were not sampled are listed and never extrapolated; indeterminate / unresolved objects
  are bounded both ways.
- NPV of production rejection = 1 - (estimated cSS among rejected / rejected).

Pre-specified primary outcome: lesion-level sensitivity for definite + probable cSS (adjudicated), by failure type, all 14 studies,
reported separately for M02-M11 and M12-M15. No threshold is changed on the basis of this analysis; changes are a later, separate,
pre-registered step tested on new patients.
