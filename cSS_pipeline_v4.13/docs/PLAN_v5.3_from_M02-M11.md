# Plan v5.3 — fixes from the M02–M11 reading (287 candidates, 61 called cSS)

Research software. Based on the reader's calls in `summary.csv` and on the exported images
(all 61 cSS images and a sample of 32 Artifact / Normal images were viewed). Implemented as opt-in CSS_V53=1
(docs/CHANGELOG_v5.3.md lists what differs from this plan); not yet run on patient data.

## What the data shows

| Reader call | n | Share | Median volume |
|---|---|---|---|
| Normal | 114 | 40 % | 46 mm³ |
| Artifact | 78 | 27 % | 126 mm³ |
| cSS | 61 | 21 % | 85 mm³ |
| Vein | 20 | 7 % | 40 mm³ |
| Near ICH | 11 | 4 % | |
| Unsure | 3 | 1 % | |

1. **Dark skull / dura inside the brain mask (the main artifact).** The v5.2.5 mask is the T1 labels grown by 5 mm,
   and the detector ignores only the outer 3 mm, so 2 mm beyond the label boundary is searched. Where the CSF is thin
   (convexity) that band is the dark inner skull. Result: band-shaped objects along the convexity.
   All 9 candidates above 3,000 mm³ are Artifact (M02-17, M03-5, M06-10, M07-12, M08-7, M09-11, M10-18, M10-24,
   M11-33; up to 41,880 mm³), and many smaller ones sit in the same black band (e.g. M03-1, -2, -4, -19).
   The largest cSS call is 830 mm³.
2. **Midline.** Normal calls concentrate in superior frontal (24) and precuneus (15): the interhemispheric fissure,
   falx and sagittal sinus (e.g. M03-18, -21, -24, -31).
3. **Orbitofrontal air–bone zone.** 20 Artifact calls in medial / lateral orbitofrontal; flagged, never removed.
4. **One cSS reported several times.** 61 cSS calls fall in only 40 patient–hemisphere–region groups; 16 groups hold
   37 of the calls. M04: 17 candidates in 7 regions, all along the same left central / precentral / postcentral sulci
   (e.g. 1, 32, 39 all "precentral"). The outlines are thin fragments of the dark band (ridge-thinned), so one
   continuous lining breaks into pieces further apart than the 3 mm merge gap.
5. **The "likely vein" tier is wrong for cSS.** 18 of 61 cSS calls are tier 3. "Off the cortex, in the CSF,
   vessel-shaped" fired on 8 of them: cSS lines the sulcus, so it is partly in the sulcal CSF by nature.
6. **Insula (13 Normal)**: dark signal at the insular surface next to the middle cerebral vessels.

## Reading decisions worth a second look (not changed here)

- **M05-7 and M05-10**: round, dark, 3 slices, inside the tissue — the shape of a microbleed, not of a lining.
  They give M05 its score of 2. M05 is 1.5 T with 3 mm slices.
- **M03-20** (34 mm³, tier 4 microbleed-like) and **M03-32**: small / thin; M03's score of 1 rests on them.
- **M06** (10 cSS): several are thin single lines in a sulcus (6, 9, 13, 23) that could be veins; score 4.
- **M11** (13 cSS): 3 mm slices at 1.5 T; shapes are hard to judge in coronal / sagittal views; score 4.
- **M02-5** is coded cSS and **M02-11** Near ICH, although both were described as infarct hemosiderin.
- Convincing cSS (broad sulcal lining in three planes): M02-2, M04-6, -12, -22, -39, -41, -48, M09-2, M10-1, -3.

## Changes, in order (each one tested on M02–M11 against the saved calls before the next)

### Step 1 — keep the search inside the cortex outline
- Search zone = cortex ribbon plus at most **1.0 mm** outside the pial boundary (now 4 mm), from the T1 labels.
- Mask growth stays (needed for registration and display) but detection no longer uses the grown band:
  voxels more than 1 mm outside the labels are never candidates.
- Skull guard: drop candidate voxels whose outward neighbourhood (2–4 mm along the pial normal) is as dark as
  the candidate itself (dark all the way out = skull, not a lining on bright CSF / cortex).
- Expected: removes the 9 giant bands and most convexity artifacts. Check: none of the 61 cSS calls lost.

### Step 2 — artifact exclusions (new rules, off by default until step 5 passes)
- **E12 extent**: one object > 3,000 mm³ or spanning > 60 mm along the surface → artifact (largest cSS call: 830 mm³).
- **E13 midline**: > 50 % of the object within 3 mm of the interhemispheric plane / falx → excluded
  (medial cSS exists; listed in excluded.csv, reported).
- **E14 orbitofrontal**: object in orbitofrontal labels and in the air–bone artifact zone → excluded.
- **Insula**: flag only (tier 4) for now; needs more cases.

### Step 3 — one cSS = one candidate
- Candidate mask = the dark band, not the ridge skeleton: grow each detection inside the cortex zone to the
  connected dark voxels (same threshold as score_css.py uses for "grown volume").
- Merge along the surface: detections whose grown masks touch, or lie within 6 mm **geodesically along the pial
  surface in the same or a directly continuous sulcus** (Destrieux labels), become one candidate. Cap 80 mm.
- The reviewer shows the merged object once; the score already counts sulci, so it should not change —
  verify on M04 (17 candidates → expected about 5–7) that left = 2 is kept.

### Step 4 — tiers
- "Off the cortex, in the CSF, vessel-shaped" no longer makes tier 3 alone; it needs continuation into white
  matter, a run to the sinus, or a tube continuing at both ends.
- New tier-4 reasons from steps 1–2 (skull band, midline, orbitofrontal).

### Step 5 — acceptance test on M02–M11 (calls are fixed, no re-reading needed)
| Measure | Now | Target |
|---|---|---|
| cSS calls still shown | 61 / 61 | 61 / 61 (or each loss explained) |
| Artifact candidates | 78 | < 25 |
| Normal candidates | 114 | < 80 |
| cSS calls in tier 3 | 18 | < 6 |
| Candidates per cSS region | 61 / 40 = 1.5 | about 1.1 |
| Patient scores (L, R, total) | — | unchanged for all 10 |

Then, and only then: detect M12–M15 and M01 with v5.3 and read them (true test; they were not used for tuning).

## Limits
- All thresholds above come from these 10 patients: they are tuned on them. M12–M15 are the only untouched cases.
- The 488 excluded objects were not rated: cSS removed by the existing rules cannot be counted from this export.
- Narrowing the zone to the cortex will lose cSS that lies only in the sulcal CSF beyond 1 mm; step 5 measures it.
- The reader's calls, not a radiologist's lesion labels, are the reference here.

## Addendum — independent blinded second look (194 candidates, reader's call hidden)

The 194 candidates not viewed before were shown shuffled, without title or call (three-plane 40 mm crops only;
not a radiologist's reading). The 61 cSS calls had already been seen with their label, so they are not in this set.

- cSS versus not-cSS: agreement on 190 of 194. Exact category: 103 of 194 (53 %).
- Most category differences do not matter for the score: 39 "Normal" (reader) were called "Vein" here,
  12 "Normal" were called "Artifact" (midline or skull band).
- Candidates worth re-opening in the reviewer (called cSS here, not by the reader):
  M04-5 (Normal), M04-15 (Unsure), M04-25 (Near ICH), M02-11 (Near ICH).
- Possible cSS, uncertain here: M04-35, M04-43, M09-5, M11-30.
- Consequences for the plan: 68 of 194 are skull band / skull base / outside-brain (step 1), about 45 are midline
  falx, sinus or deep midline veins (E13), and round 1–2 voxel dark dots are veins seen end-on (tier 3 is right for them).
