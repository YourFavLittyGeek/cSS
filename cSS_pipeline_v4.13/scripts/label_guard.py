#!/usr/bin/env python3
"""label_guard.py - Phase 3D (part 5): the legacy labels/ tools (train_ranker.py, evaluate.py, classify_surface_patches.py train /
lopo-manifest) read the separate labels/ ecosystem (expert_import, consensus, label_missed, study_meta). Those labels are NOT the Phase 3A
expert ground truth: no designated reviewer roles, no completed-review consensus, no blinding provenance, and study_meta.csv splits by
STUDY, not by patient. These tools therefore refuse to run unless explicitly started as unverified research (--research-unverified);
every output they then write is stamped so it can never be mistaken for a validated result. Primary training and evaluation use the
Percival engine (call ledger + eligibility + locked patient-level split + leakage audit)."""
import sys

FLAG = "--research-unverified"
STAMP = dict(label_provenance="labels/ ecosystem - NOT Phase 3A expert ground truth (no roles, no completed-review consensus, no blinding "
                              "provenance; study-level split)", research_only_unverified=True)


def require(tool):
    if FLAG not in sys.argv:
        sys.exit(f"{tool}: refused - it reads labels/ (not the Phase 3A expert ground truth: no roles, consensus or blinding provenance; "
                 f"study-level split). Primary training/evaluation: Percival (Training Center). For unverified research use, add {FLAG}.")
    sys.argv.remove(FLAG)
    print(f"{tool}: UNVERIFIED RESEARCH RUN - labels/ are not Phase 3A expert ground truth; outputs are stamped research_only_unverified", flush=True)
