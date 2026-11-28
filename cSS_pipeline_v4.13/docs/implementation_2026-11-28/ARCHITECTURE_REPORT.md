# Architecture report — PERCIVAL after the 2026-11-28 corrections

```mermaid
flowchart TD
  classDef new fill:#dbeafe,stroke:#1d4ed8;
  classDef impl fill:#dff0d8,stroke:#3c763d;
  classDef planned fill:#f5f5f5,stroke:#999,stroke-dasharray: 5 5;
  MRI[SWI + T1/FLAIR] --> PRE[dcm2niix · SynthSeg/recon-all · rigid SWI→T1]:::impl
  PRE --> ALBUS[ALBUS detect_css.py - pinned detector\ncandidates (ridge core) + dark map]:::impl
  ALBUS --> EXT[ALBUS outline refinement refine.py\nextent ≤ 5 mm in the dark map + measures]:::new
  ALBUS --> REV[blind expert review\ncalls · missed-cSS marks]:::impl
  EXT --> REV
  REV --> LED[call ledger · ground truth\nexpert records only]:::impl
  REV --> MK[marks: enclosed area · 3-D extent\ncurrent fate]:::new
  ALBUS --> NOX[NOX 30 measurements]:::impl
  ALBUS --> LUMOS[LUMOS patch model]:::impl
  MK --> LUMOS
  MK --> NOX
  LED --> GATE[training-readiness gate]:::new
  GATE --> VAL[validation 2.0: stratified shared folds\nfold AUC · paired choice · within-fold calibration]:::new
  NOX --> VAL
  LUMOS --> VAL
  ALBUS --> VAL
  VAL --> PC[PERCIVAL CORE meta-model\n+ informative flag]:::new
  PC --> TEST[locked test: candidate · patient · lesion\nALBUS on the same candidates]:::new
  TEST --> ACC[acceptance · every consultation uses the milestone]:::new
  ACC --> REG[registry · human promotion]:::impl
  REG --> SCORE[PERCIVAL SCORE 0-100]:::impl
  EXT -.-> SH[SHADOW: extent_* candidate variables]:::new
  SH -.->|confirmed + approved only| NOX
  LED --> PEN[PENSIEVE index: expert vs prediction tables]:::impl
  SCORE --> PEN
  DL[deep-learning segmentation]:::planned
```

| Engine | Responsibility | Code | Changed now |
|---|---|---|---|
| ALBUS | finds and ranks candidates; outlines them (core + extent) | `scripts/detect_css.py` (pinned, unchanged), `uengine/imaging/refine.py` (new), `app/albus_redetect.py` | extent outline; re-detection of marks grows them to their true extent and records their current fate |
| NOX | quantitative measurements | `uengine/percival/component_api.py`, meta CHAR set | family choice by paired discrimination; extent measures offered via SHADOW (not adopted silently) |
| LUMOS | image appearance | `uengine/percival/cnn.py`, `learners.py`, `imaging/patches.py` | family choice by paired discrimination; mark patches from the 3-D object; marks on shown candidates left out by current fate |
| PERCIVAL CORE | the only combiner, final score | `meta.py`, `nested.py`, `validation.py` (new) | validation 2.0, informative flag, like-for-like acceptance, patient/lesion test levels |
| PENSIEVE | research memory | `uengine/pensieve_index.py` (per project), Settings card | Settings shows the real index (counts, separation check, rebuild) |
| SHADOW | governed experiments | `uengine/shadow_governed.py`, `percival_gui._shadow_rows` | receives real development rows (was 0); extent variables |

Data safety layers added: `app/safe_json.py` (state files), `app/keystore.py` + `identity.py` (vault encrypted at rest).

**Remaining disconnected / legacy components** (unchanged, documented in the audit): legacy `uengine/{albus,nox,lumos,percival_core}.py`
(off-by-default comparison baseline), `uengine/transfer_manager.py` + `unified_transfer_engine.py` (still read by Settings › Transfer and the
quit check), `uengine/patient_split.py`, `app/study_split.py` (uScore gate), `/api/wizard/*`, `/api/migration/*`, `/api/legacy/*`, hidden
prototype screens (training_gui, unified_gui, shadow_engine_gui, image_ml_gui), root-level `/app/` copy, `/api/percival/identity` (missing
function). None of them feeds the PERCIVAL score.
