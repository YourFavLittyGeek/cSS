# PERCIVAL v5.25-dev — AUDIT OF TRAINING CENTER INFRASTRUCTURE & JOB RUNNER

**Document ID:** `AUDIT-TRAIN-v525`  
**Date:** 2026-11-22  
**Auditor:** Principal Software Quality Auditor & Senior Python Systems Engineer  
**Scope:** `app/percival_gui.py`, `app/css_app.py`, `unified_engine/uengine/percival/eligibility.py`  
**Classification:** Independent Forensic Audit Report  

---

## 1. Executive Summary & Infrastructure Verdict

The Training Center in Percival v5.25-dev is the administrative and operational nexus for executing local model retraining, tracking job progress, managing hardware resources, and governing model promotions.

### Primary Audit Verdict:
1. **Deterministic Finite State Machine:** Job states (`idle`, `preparing`, `running`, `finished`, `failed`, `cancelled`, `interrupted`) are governed by a thread-safe state machine. Invalid state transitions (e.g., jumping from `finished` directly back to `running`) raise explicit runtime exceptions.
2. **Stage-Aware Stall Detection:** Instead of a single static timeout, the engine implements stage-specific maximum stall thresholds (`STALL_S`), providing generous tolerances for compute-intensive nested cross-fitting ($900\text{ s}$) while maintaining rapid failure detection for dataset gathering ($300\text{ s}$) and registry recording ($120\text{ s}$).
3. **Atomic File Transactions:** All serialized state files, candidate metadata, and model definitions use process- and thread-specific temporary files (`.tmp`) followed by atomic POSIX filesystem renaming (`os.replace`), preventing corruption from concurrent read/write operations.
4. **Transparent Hardware Accounting:** The system explicitly reports CPU and resident RAM usage via `resource.getrusage`. GPU utilization is honestly reported as `"not used (CPU engine)"` rather than displaying mock or synthetic telemetry.

---

## 2. Job Lifecycle & State Machine Architecture

### 2.1 State Transitions (`percival_gui.py`)
State transitions are guarded by `LOCK` and verified against the transition matrix:
```python
TRANSITIONS = dict(
    idle={"preparing"},
    preparing={"running", "failed", "cancelled"},
    running={"finished", "failed", "cancelled"},
    finished={"preparing"},
    failed={"preparing"},
    cancelled={"preparing"},
    interrupted={"preparing"}
)
```

```
       +------------+
       |    IDLE    |
       +------------+
             |
             v
      +--------------+  (Error / Cancel)  +------------------------+
      |  PREPARING   | -----------------> | FAILED / CANCELLED /   |
      +--------------+                    | INTERRUPTED            |
             |                            +------------------------+
             v                                        ^
       +-------------+                                |
       |   RUNNING   | -------------------------------+
       +-------------+
             | (Completion)
             v
      +--------------+
      |   FINISHED   |
      +--------------+
```

### 2.2 Cooperative Cancellation Protocol
Cancellation is initiated via `/api/percival/cancel`. Rather than forcefully killing background threads (which risks leaving half-written files or corrupt SQLite locks), Percival implements cooperative interruption:
- When `JOB["cancel"] == True`, the next execution of `log(msg, prog)` raises `Cancelled("cancelled by " + str(user))`.
- The exception handler cleanly transitions the state machine to `cancelled`, removes intermediate scratch data, and preserves prior stable model versions.

---

## 3. Stage-Aware Stall Detection & Progress Tracking

Retraining on 30+ patient cohorts with multi-fold nested CNNs requires significant CPU compute. A naive timeout triggers false-positive failure alarms during intensive cross-fitting.
Percival solves this by segmenting training into stages with calibrated stall budgets:

| Training Stage | Identifier Regex | Stall Timeout (`STALL_S`) | Operational Content |
|---|---|---|---|
| `preparing` | `dataset`, `eligible`, `started` | 300 s (5 min) | Extracting candidate CSVs, verifying review labels |
| `components` | `component`, `image models`, `char` | 600 s (10 min) | Level-0 model fitting and feature extraction |
| `nested` | `nested` | 900 s (15 min) | Outer $5 \times$ inner $3$-fold nested cross-fitting |
| `discovery` | `meta-model discovery` | 600 s (10 min) | Evaluating 7 meta-models via 1-SE rule |
| `final` | `final fit` | 600 s (10 min) | Refitting chosen model on full development set |
| `evaluation` | `locked test` | 300 s (5 min) | Evaluating frozen model on locked test cohort |
| `registering` | `registered` | 120 s (2 min) | Serializing model JSON and updating ledger |

Every log call updates `JOB["heartbeat"] = time.time()`. If `now - heartbeat > STALL_S[stage]`, the monitor marks the job as stalled.

---

## 4. Resource Telemetry & ETA Estimation

### 4.1 Process Accounting
In `_proc_resources()`:
```python
ru = resource.getrusage(resource.RUSAGE_SELF)
cpu_t = ru.ru_utime + ru.ru_stime
rss_mb = ru.ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)
```
- Real physical resident set size (RSS) is tracked directly from the kernel.
- CPU engine status is transparently exposed: `"gpu": "not used (CPU engine)"`.

### 4.2 ETA Calculation
Estimated time to completion (ETA) is calculated using a rolling window of the last 60 progress/time tuples:
$$\text{Rate} = \frac{\Delta \text{progress}}{\Delta \text{time}} = \frac{p_t - p_{t - \Delta t}}{\Delta t}$$
$$\text{ETA (seconds)} = \frac{1.0 - p_t}{\max(\text{Rate}, \epsilon)}$$
This rolling estimate dampens transient fluctuations between fast tabular stages and compute-intensive CNN backpropagation.

---

## 5. Candidate Eligibility & Quality Control (`eligibility.py`)

A study is permitted into the development/test dataset **only** if it satisfies rigorous inclusion criteria:
1. **Review Completeness:** Study must have finalized expert reviews (`*_calls.csv` and `*_final.json`).
2. **Reviewer Agreement:** If multiple reviewers evaluated the study, candidate calls must agree or follow defined consensus rules. Conflicted candidates are excluded from training.
3. **Anatomical Verification:** Brain segmentation must be valid; missing cortex or skull-strip failures are excluded.
4. **Candidate Count Thresholds:** Governed by `CSS_LEARN_MIN = "8,40,6"` (minimum 8 reviewed patients, 40 total candidates, 6 positive cSS instances). Retraining cannot trigger on inadequate sample support.

---

## 6. Audit Verdict

**Training Center Subsystem: PASS**  
The state machine, stage-specific heartbeat stall monitor, cooperative cancellation, atomic file handling, and eligibility guards provide robust, production-grade reliability for local neuroimaging model training.
