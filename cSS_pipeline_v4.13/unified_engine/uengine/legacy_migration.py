"""legacy_migration.py - Autonomous Legacy Research Data Discovery & Migration Engine for PERCIVAL.

Provides non-destructive discovery of historical cSS and Percival pipeline runs, MRI datasets,
candidate calls, and radiologist reviews across the user's filesystem, offering 4 structured migration options:
- Option A: Reprocess from original MRI (v5.25 pipeline)
- Option B: Re-evaluate historical candidates (score with ALBUS/LUMOS/NOX without re-running segmentation)
- Option C: Ingest into PENSIEVE memory only (register for historical context & training)
- Option D: Archive directly to external Data Vault
"""

import glob
import hashlib
import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


class LegacyMigrationEngine:
    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)
        self.app_data_dir = os.path.join(self.base_dir, "app_data")
        os.makedirs(self.app_data_dir, exist_ok=True)
        self.history_file = os.path.join(self.app_data_dir, "migration_history.jsonl")
        self.state_file = os.path.join(self.app_data_dir, "migration_state.json")

    def discover_legacy_data(self, search_roots: Optional[List[str]] = None) -> Dict[str, Any]:
        """Perform a strictly read-only discovery of legacy research datasets."""
        roots = search_roots or [
            self.base_dir,
            os.path.expanduser("~/cSS_pipeline"),
            os.path.expanduser("~/cSS_pipeline_v4.13"),
            os.path.expanduser("~/percival_workspace"),
            os.path.expanduser("~/css_project"),
            os.path.expanduser("~/cSS_experimental"),
        ]

        discovered_studies: Dict[str, Dict[str, Any]] = {}

        for r in roots:
            abs_r = os.path.abspath(os.path.expanduser(r))
            if not os.path.isdir(abs_r):
                continue
            base_depth = abs_r.rstrip(os.sep).count(os.sep)

            for root_dir, dirs, files in os.walk(abs_r):
                current_depth = root_dir.rstrip(os.sep).count(os.sep) - base_depth
                if current_depth > 4:
                    dirs.clear()
                    continue
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("Library", "Trash", "node_modules", "DerivedData", "build", "dist", ".percival_backup")]

                for f in files:
                    # 1. Candidate detections
                    if f.endswith("_candidates.csv"):
                        study_code = f.replace("_candidates.csv", "")
                        st = discovered_studies.setdefault(study_code, {
                            "study_code": study_code,
                            "root_dir": root_dir,
                            "candidates_csv": None,
                            "candidates_nii": None,
                            "radiologist_calls": [],
                            "raw_mri": [],
                            "segmentations": [],
                            "pensieve_records": False,
                            "total_bytes": 0,
                            "modified": 0,
                        })
                        p = os.path.join(root_dir, f)
                        st["candidates_csv"] = p
                        sz = os.path.getsize(p)
                        st["total_bytes"] += sz
                        st["modified"] = max(st["modified"], os.path.getmtime(p))

                    elif f.endswith("_candidates.nii.gz"):
                        study_code = f.replace("_candidates.nii.gz", "")
                        st = discovered_studies.setdefault(study_code, {
                            "study_code": study_code,
                            "root_dir": root_dir,
                            "candidates_csv": None,
                            "candidates_nii": None,
                            "radiologist_calls": [],
                            "raw_mri": [],
                            "segmentations": [],
                            "pensieve_records": False,
                            "total_bytes": 0,
                            "modified": 0,
                        })
                        p = os.path.join(root_dir, f)
                        st["candidates_nii"] = p
                        sz = os.path.getsize(p)
                        st["total_bytes"] += sz
                        st["modified"] = max(st["modified"], os.path.getmtime(p))

                    # 2. Radiologist reviews
                    elif "_calls_" in f and f.endswith(".csv"):
                        study_code = f.split("_calls_")[0]
                        st = discovered_studies.setdefault(study_code, {
                            "study_code": study_code,
                            "root_dir": root_dir,
                            "candidates_csv": None,
                            "candidates_nii": None,
                            "radiologist_calls": [],
                            "raw_mri": [],
                            "segmentations": [],
                            "pensieve_records": False,
                            "total_bytes": 0,
                            "modified": 0,
                        })
                        p = os.path.join(root_dir, f)
                        st["radiologist_calls"].append(p)
                        sz = os.path.getsize(p)
                        st["total_bytes"] += sz
                        st["modified"] = max(st["modified"], os.path.getmtime(p))

                    # 3. Raw MRI series
                    elif (f.endswith(".nii") or f.endswith(".nii.gz")) and ("SWI" in f.upper() or "BRAIN" in f.upper()):
                        p = os.path.join(root_dir, f)
                        sz = os.path.getsize(p)
                        # Derive study code from parent or filename
                        code = os.path.basename(root_dir)
                        if code in discovered_studies:
                            discovered_studies[code]["raw_mri"].append(p)
                            discovered_studies[code]["total_bytes"] += sz

        items = list(discovered_studies.values())
        total_discovered_bytes = sum(it["total_bytes"] for it in items)

        return {
            "total_studies": len(items),
            "total_bytes": total_discovered_bytes,
            "total_mb": round(total_discovered_bytes / (1024**2), 2),
            "total_gb": round(total_discovered_bytes / (1024**3), 2),
            "studies": items,
        }

    def create_migration_plan(
        self,
        discovered_studies: List[Dict[str, Any]],
        default_strategy: str = "import_pensieve_only",
        custom_strategies: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Generate structured plan mapping each legacy study to one of 4 options."""
        custom = custom_strategies or {}
        valid_strategies = {
            "reprocess_full": "Option A: Reprocess from original MRI (v5.25 pipeline)",
            "reevaluate_candidates": "Option B: Re-evaluate historical candidates (score with v5.25)",
            "import_pensieve_only": "Option C: Ingest into PENSIEVE memory only",
            "archive_to_vault": "Option D: Archive directly to external Data Vault",
        }

        plan_items = []
        counts = {k: 0 for k in valid_strategies}

        for st in discovered_studies:
            code = st["study_code"]
            strat = custom.get(code, default_strategy)
            if strat not in valid_strategies:
                strat = "import_pensieve_only"

            counts[strat] += 1
            plan_items.append({
                "study_code": code,
                "strategy": strat,
                "strategy_label": valid_strategies[strat],
                "files_count": (1 if st.get("candidates_csv") else 0) + len(st.get("radiologist_calls", [])) + len(st.get("raw_mri", [])),
                "total_bytes": st.get("total_bytes", 0),
                "details": st,
            })

        return {
            "total_studies": len(plan_items),
            "strategy_breakdown": counts,
            "plan_items": plan_items,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def execute_migration(
        self,
        plan: Dict[str, Any],
        vault_dir: Optional[str] = None,
        pensieve_db_path: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Safely execute the approved migration plan."""
        plan_items = plan.get("plan_items", [])
        migrated = []
        errors = []

        for item in plan_items:
            code = item["study_code"]
            strat = item["strategy"]
            details = item["details"]

            if dry_run:
                migrated.append({"study_code": code, "action": f"DRY_RUN: {strat}"})
                continue

            try:
                if strat == "archive_to_vault":
                    if not vault_dir or not os.path.isdir(vault_dir):
                        raise RuntimeError("Cannot archive to vault: Data Vault directory not connected.")
                    target_dir = os.path.join(vault_dir, "archive", code)
                    os.makedirs(target_dir, exist_ok=True)
                    # Copy candidates and calls
                    if details.get("candidates_csv") and os.path.exists(details["candidates_csv"]):
                        shutil.copy2(details["candidates_csv"], target_dir)
                    for c in details.get("radiologist_calls", []):
                        if os.path.exists(c):
                            shutil.copy2(c, target_dir)
                    for r in details.get("raw_mri", []):
                        if os.path.exists(r):
                            shutil.copy2(r, target_dir)

                elif strat == "import_pensieve_only":
                    # Register into review or Pensieve
                    review_dir = os.path.join(self.base_dir, "review")
                    os.makedirs(review_dir, exist_ok=True)
                    if details.get("candidates_csv") and os.path.exists(details["candidates_csv"]):
                        dest_csv = os.path.join(review_dir, f"{code}_candidates.csv")
                        shutil.copy2(details["candidates_csv"], dest_csv)
                    for c in details.get("radiologist_calls", []):
                        if os.path.exists(c):
                            shutil.copy2(c, review_dir)

                elif strat == "reevaluate_candidates":
                    # Place in review directory ready for scoring
                    review_dir = os.path.join(self.base_dir, "review")
                    os.makedirs(review_dir, exist_ok=True)
                    if details.get("candidates_csv") and os.path.exists(details["candidates_csv"]):
                        shutil.copy2(details["candidates_csv"], os.path.join(review_dir, f"{code}_candidates.csv"))

                elif strat == "reprocess_full":
                    # Stage raw MRI in app_data/staging for processing
                    staging_dir = os.path.join(self.app_data_dir, "staging", code)
                    os.makedirs(staging_dir, exist_ok=True)
                    for r in details.get("raw_mri", []):
                        if os.path.exists(r):
                            shutil.copy2(r, staging_dir)

                migrated.append({"study_code": code, "strategy": strat, "status": "success"})

            except Exception as e:
                errors.append({"study_code": code, "strategy": strat, "error": str(e)})

        # Log results
        result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total": len(plan_items),
            "migrated": len(migrated),
            "errors_count": len(errors),
            "migrated_items": migrated,
            "errors": errors,
            "dry_run": dry_run,
        }

        try:
            with open(self.history_file, "a") as f:
                f.write(json.dumps(result) + "\n")
        except Exception:
            pass

        return result

    def get_migration_history(self) -> List[Dict[str, Any]]:
        history = []
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            history.append(json.loads(line))
            except Exception:
                pass
        return history
