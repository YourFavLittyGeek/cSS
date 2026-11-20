"""uengine.prototype - the Unified Score components and fusion layer (research software; not for clinical use).

  components.MathComponent             MATH: verbatim detector score_v4 / evidence / rules / tiers (+ a 2-parameter monotone recalibration)
  components.CharacteristicsComponent  CHARACTERISTICS: validated measured inputs, statuses, missingness, extrapolation flags
  components.IncrementComponent        PAST EXPERIENCE: learned log-odds increment beyond MATH (offset model)
  components.StandaloneLearnedComponent / NullPastExperience   replaceable alternatives (ablations)
  fusion.UnifiedScorer                 fusion layer: unified probability + interval + category + full trace per candidate
  patient.patient_summary              patient-level layer (separate type; never fed back into candidate scoring)
  inputs.sanitize                      input validation (types, inf, strings, ranges, duplicates, forbidden columns)
"""
PROTOTYPE_VERSION = "uengine-fusion/1.0"
