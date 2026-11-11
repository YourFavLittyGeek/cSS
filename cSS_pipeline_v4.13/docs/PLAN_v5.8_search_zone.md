# Plan v5.8 - item 1: fix the search zone at the source (no code yet)

Research software; expert review required. Nothing here is implemented. Fitted/checked on M02-M11 only; M12-M15 and M01 stay untouched.

## 1. What the detector does today (detect_css.py)
- shell = brain mask AND pial band (-3.5 mm in tissue .. +4.0 mm outward) minus white matter and deep nuclei
- zone  = shell minus a 3 mm rim at the brain-mask edge. With the T1 route the mask is labels + 5 mm, so 2 mm beyond the labels is searched everywhere.
- thresholds: ridge percentiles (85th strong / 80th weak) taken over the SHELL; darkness z against the local cortex mean
- everything outside the cortex, in the fissure or on the skull is removed AFTERWARDS by fitted rules: E13, E15, E17, E19, E20, E21, E22, E25
  (8 rules, about 12 thresholds, all set on the same 10 patients, most "just beyond the most extreme cSS").

## 2. What is wrong with that
1. The +4 mm outward band is right in a sulcus (CSF between two banks) and wrong on the convexity, where +4 mm outward is dura and inner table.
2. The interhemispheric fissure is searched like any sulcus although its content (falx, sinus, bridging veins) is never cSS.
3. Long dark structures outside the cortex are generated, merged with real objects (cross-call merges), and only then judged.
4. v5.3.0 narrowed the zone and lost 3 cSS; v5.3.1 trimmed object voxels and lost 3 cSS below the size gates. Both changed the OBJECTS.
   Lesson: thresholds and object growth must stay as they are; only WHERE A SEED MAY START may change.

## 3. Honest expectation before any work
zone_probe.py (v5.7) already showed that, with today's rules on, almost no SHOWN object lies in the outside / infratentorial compartments: the
strips you saw in the reviewer were the 20 % audit sample of EXCLUDED objects. So this item will probably remove few of the 117 non-cSS objects
still shown. Its real value is different:
- 8 fitted after-the-fact rules are replaced by one anatomical definition -> fewer thresholds to fail on M12-M15 / M01
- fewer raw components and fewer wrong merges (a skull strip can no longer be joined to a cSS piece)
- the medial non-cSS (37 of 117 in medial regions) are the one group where a gain is plausible
If step A shows no gain and no simplification, this item is dropped and item 2 (Sylvian fissure, 26 of 117) goes first.

## 4. The proposed definition (three compartments, anatomy only)
For every voxel of the shell, from the labels already on the SWI grid:
- RIBBON   inside labelled cortex (pial_sd <= 0)
- SULCAL   CSF with cortex of the SAME hemisphere within R mm in two opposing directions (a sulcus: bank - CSF - bank)
- CONVEX   CSF outward of the pial surface with no opposing bank (faces dura / skull)
- FISSURE  CSF with LEFT and RIGHT cortex both within 3 mm (the existing E25 construction, DUALC)
Seed rule: a strong seed may start only in RIBBON or SULCAL. Weak voxels may still grow anywhere in today's zone (objects keep their shape).
Object rule (replaces E13/E15/E17/E22/E25): an object is kept if at least F of its voxels are RIBBON or SULCAL.
New numbers: R (sulcus half-width) and F. Target: R from anatomy (sulcal width, e.g. 4 mm = today's band), F fitted with a margin >= 10 %.

## 5. Steps, each with a stop
A. Read-only probe on the CURRENT detection (new script zone2_probe.py, no detector change). Per shown and excluded object of M02-M11: share of
   voxels and of strong seeds in RIBBON / SULCAL / CONVEX / FISSURE. Output: how many of the 117 shown non-cSS and of the 56 cSS fall under
   each F; which of today's excluded objects (by rule) the single definition reproduces. ~10 min on the Mac.
   STOP if any cSS has < F + 10 % margin for every useful F, or if the gain is < 5 shown non-cSS AND fewer than 6 of the 8 rules become redundant.
B. Opt-in switch CSS_ZONE2=1 (default off; output identical when off). Seed restriction + object rule; E13/E15/E17/E22/E25 stay computed and
   recorded but do not exclude when the switch is on. Phantom tests: no true lesion lost (PH3, skull phantom, fissure phantom); a skull strip
   touching a lesion no longer merges with it.
C. Experiment on copies (run_experiment.py + compare_pipelines.py, M02-M11): must give 56/56 cSS shown, no new cross-call merge, shown non-cSS
   not higher than today. Report per study and per replaced rule. STOP and report if any cSS is lost.
D. Only then: your decision to make it the default, redetect, re-read the changed objects.
E. M12-M15 + M01 once, frozen, whichever variant is the default by then.

## 6. Risks
- Medial cSS on the mesial surface is real (superior frontal, precuneus, cuneus): it must stay RIBBON; step A checks every medial cSS call.
- Label accuracy: with 3 mm slices or a 1-2 mm registration slip, RIBBON shifts; QC label shift > 1.5 mm -> the rule is not applied (as E8 today).
- SWI-only route (no T1 labels): definition not applied, as the v5.3 rules today.
- A sulcus wider than 2R (atrophy, common in CAA) would read CONVEX: step A reports the SULCAL share of cSS by patient to catch this.

## 7. What this item does not address
Sylvian fissure vessels (item 2), air artifact map (item 3), fragment grouping for reading (item 4), vein continuity (item 5).
