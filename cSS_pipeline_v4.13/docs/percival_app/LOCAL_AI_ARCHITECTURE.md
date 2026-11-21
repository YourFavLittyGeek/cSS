# Percival - local AI architecture (what runs where, and how it is verified)

Percival's MRI AI is the user's own: every model is trained, stored and run on the user's computer from the project's own MRI and
expert reviews. Claude (the software developer) is not part of the running application and is never called by it.

## What is local

| Item | Where | Notes |
|---|---|---|
| MRI processing, candidate detection, MATH | `scripts/` (+ FreeSurfer installed locally) | numpy / scipy / nibabel |
| Feature / predictor extraction | `unified_score/uscore`, `detect_css.py` | |
| Image patches | `unified_engine/uengine/imaging/patches.py` -> `<project>/unified_engine/percival/cache/` | |
| Model training (all components, meta-model, calibration) | `unified_engine/uengine/percival/` | pure numpy, CPU, fixed seeds; no PyTorch / scikit-learn / XGBoost; no pretrained weights downloaded |
| Model weights and registry | `<project>/unified_engine/percival/registry/vNNN/model.json` | plain JSON, versioned, never overwritten |
| Predictions | `<project>/unified_engine/percival/scores/`, `ledger/` | immutable ledger |
| Expert labels and review snapshots | `<project>/review/`, `<project>/unified_engine/percival/reviews/` | |
| Patient / study identity | encrypted local vault (`identity.py`) | Standard / Incognito modes |
| App and reviewer servers | `127.0.0.1` only | |

There is no remote database, no cloud training or inference, no telemetry and no external AI API. Learning on a project's MRI needs a
one-time local switch (`app_data/ml_authorization.json`, audited); synthetic projects never need it.

## Offline operation
After the Python environment, FreeSurfer and its licence are installed (first-run Setup wizard), import, processing, review, training
and scoring need no network. Percival ships no model files to download: models are created by training cycles on the computer.

## Verification (not a configuration flag)
- `tests/check_local_only.py`
  - **static scan** of `app/`, `scripts/`, `unified_score/` and (since v5.23) `unified_engine/`: no network library (`requests`,
    `urllib.request`, `http.client`, `curl`, `wget`, ...), no external host in code, no external `<script src>`; servers bind to
    127.0.0.1. One documented exception: `scripts/run_lemon.sh` (optional public-dataset downloader, never called by the app).
  - **runtime network guard**: the Processing Manager, Unified-Score app, **Percival engine** (training + scoring) and **Percival app /
    GUI** tests run with every non-loopback connection refused and logged (`tests/netguard/sitecustomize.py`); the check fails if any
    process attempted one.
- `tests/check_percival.py` also scores with `socket.socket.connect` blocked inside the process.

Limits of this verification: it covers the code paths exercised by the tests and the files scanned; a dependency installed later could
add network code. Re-run `bash tests/run_uscore_tests.sh` after changing the environment.

## Development data rule
During Claude-assisted development only synthetic data were used (generated phantoms and synthetic cohorts). No clinical MRI or
identifier was opened, uploaded or copied.
