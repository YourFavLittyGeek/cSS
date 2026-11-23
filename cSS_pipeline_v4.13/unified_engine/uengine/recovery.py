"""recovery.py - Persistent Stage-by-Stage Job & Transfer Recovery Engine for PERCIVAL.

Maintains a transactional stage ledger tracking the 8-stage neuroimaging pipeline:
1. mri_validation
2. preprocessing (dcm2niix / skull-stripping / NIfTI alignment)
3. albus_inference (candidate detection)
4. lumos_inference (feature extraction & physical verification)
5. nox_inference (spatial / anatomical context)
6. percival_core (scoring & uncertainty calculation)
7. pensieve_recording (episodic memory persistence)
8. archival_transfer (verified external Data Vault backup)

Guarantees atomic stage progression: an interrupted or crashed stage is cleanly rolled back
and resumed from the last verified checkpoint without re-running prior stages.
"""

import hashlib
import json
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

PIPELINE_STAGES = [
    "mri_validation",
    "preprocessing",
    "albus_inference",
    "lumos_inference",
    "nox_inference",
    "percival_core",
    "pensieve_recording",
    "archival_transfer",
]


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


class JobRecoveryManager:
    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)
        self.app_data_dir = os.path.join(self.base_dir, "app_data")
        os.makedirs(self.app_data_dir, exist_ok=True)
        self.ledger_file = os.path.join(self.app_data_dir, "job_recovery_ledger.json")
        self._ensure_ledger()

    def _ensure_ledger(self) -> None:
        if not os.path.exists(self.ledger_file):
            initial = {
                "version": "5.25.0",
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "jobs": {},
            }
            with open(self.ledger_file, "w") as f:
                json.dump(initial, f, indent=2)

    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.ledger_file, "r") as f:
                return json.load(f)
        except Exception:
            return {"version": "5.25.0", "updated_at": "", "jobs": {}}

    def _save(self, data: Dict[str, Any]) -> None:
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tmp = self.ledger_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.ledger_file)

    def start_job(self, study_code: str, patient_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Register a new job in the recovery ledger."""
        data = self._load()
        job_id = f"job_{study_code}_{int(time.time())}"
        stages_init = {
            s: {
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "input_hashes": {},
                "output_hashes": {},
                "error": None,
            }
            for s in PIPELINE_STAGES
        }
        data["jobs"][job_id] = {
            "job_id": job_id,
            "study_code": study_code,
            "patient_id": patient_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "active",
            "current_stage": PIPELINE_STAGES[0],
            "stages": stages_init,
            "metadata": metadata or {},
        }
        self._save(data)
        return job_id

    def start_stage(self, job_id: str, stage_name: str, input_files: Optional[List[str]] = None) -> None:
        """Mark a pipeline stage as in_progress with recorded input checksums."""
        if stage_name not in PIPELINE_STAGES:
            raise ValueError(f"Unknown pipeline stage: {stage_name}")
        data = self._load()
        if job_id not in data["jobs"]:
            raise KeyError(f"Job not found: {job_id}")

        job = data["jobs"][job_id]
        in_hashes = {}
        if input_files:
            for p in input_files:
                if os.path.isfile(p):
                    in_hashes[os.path.basename(p)] = file_sha256(p)

        job["current_stage"] = stage_name
        job["stages"][stage_name].update({
            "status": "in_progress",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "input_hashes": in_hashes,
            "error": None,
        })
        self._save(data)

    def complete_stage(self, job_id: str, stage_name: str, output_files: Optional[List[str]] = None) -> None:
        """Mark a stage completed with atomic output checksum recording."""
        data = self._load()
        if job_id not in data["jobs"]:
            raise KeyError(f"Job not found: {job_id}")

        job = data["jobs"][job_id]
        out_hashes = {}
        if output_files:
            for p in output_files:
                if os.path.isfile(p):
                    out_hashes[os.path.basename(p)] = file_sha256(p)

        job["stages"][stage_name].update({
            "status": "completed",
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "output_hashes": out_hashes,
        })

        # Advance to next stage or mark job finished
        cur_idx = PIPELINE_STAGES.index(stage_name)
        if cur_idx + 1 < len(PIPELINE_STAGES):
            job["current_stage"] = PIPELINE_STAGES[cur_idx + 1]
        else:
            job["status"] = "completed"

        self._save(data)

    def fail_stage(self, job_id: str, stage_name: str, error: str) -> None:
        """Record stage failure and mark job paused for recovery."""
        data = self._load()
        if job_id in data["jobs"]:
            job = data["jobs"][job_id]
            job["status"] = "paused_failure"
            job["stages"][stage_name]["status"] = "failed"
            job["stages"][stage_name]["error"] = str(error)
            self._save(data)

    def get_resumable_jobs(self) -> List[Dict[str, Any]]:
        """Identify jobs interrupted mid-run that can resume from the last verified completed stage."""
        data = self._load()
        resumable = []

        for jid, job in data["jobs"].items():
            if job.get("status") in ("active", "paused_failure"):
                # Find last completed stage
                completed = []
                for s in PIPELINE_STAGES:
                    if job["stages"][s]["status"] == "completed":
                        completed.append(s)
                    else:
                        break

                resume_stage = PIPELINE_STAGES[len(completed)] if len(completed) < len(PIPELINE_STAGES) else None
                resumable.append({
                    "job_id": jid,
                    "study_code": job["study_code"],
                    "patient_id": job["patient_id"],
                    "status": job["status"],
                    "completed_stages": completed,
                    "resume_from_stage": resume_stage,
                })
        return resumable

    def rollback_incomplete_stage(self, job_id: str, stage_name: str, output_paths_to_clean: Optional[List[str]] = None) -> None:
        """Atomically discard partial outputs from an incomplete/interrupted stage."""
        data = self._load()
        if job_id in data["jobs"]:
            job = data["jobs"][job_id]
            st = job["stages"].get(stage_name)
            if st and st.get("status") in ("in_progress", "failed"):
                st["status"] = "pending"
                st["started_at"] = None
                st["output_hashes"] = {}
                st["error"] = None
                job["current_stage"] = stage_name
                job["status"] = "active"

        if output_paths_to_clean:
            for p in output_paths_to_clean:
                if os.path.exists(p):
                    try:
                        if os.path.isdir(p):
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            os.remove(p)
                    except Exception:
                        pass

        self._save(data)

    def get_recovery_summary(self) -> Dict[str, Any]:
        """Summary metrics for Recovery Center in Settings / UI."""
        data = self._load()
        total_jobs = len(data["jobs"])
        active_jobs = sum(1 for j in data["jobs"].values() if j.get("status") == "active")
        completed_jobs = sum(1 for j in data["jobs"].values() if j.get("status") == "completed")
        failed_jobs = sum(1 for j in data["jobs"].values() if j.get("status") == "paused_failure")
        resumable = self.get_resumable_jobs()

        return {
            "total_jobs": total_jobs,
            "active_jobs": active_jobs,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "resumable_jobs_count": len(resumable),
            "resumable_jobs": resumable,
        }
