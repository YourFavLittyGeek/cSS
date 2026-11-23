#!/usr/bin/env python3
"""Legacy Study Discovery Service
Scans configured directories for MRI studies (DICOM/NIfTI) that are not yet
registered in the Pensieve database and registers them.
"""
import os
import json
import pathlib
from typing import List

# Placeholder import – actual implementation would use the Pensieve API
try:
    from uengine.pensieve import PensieveCoreMemory
except Exception:
    PensieveCoreMemory = None  # type: ignore

# Directories to scan – could be extended via settings
SCAN_ROOTS = [
    os.path.expanduser("~/PercivalData"),
    "/Volumes"
]

def is_dicom_folder(path: str) -> bool:
    # Simple heuristic: contains .dcm files
    return any(f.lower().endswith('.dcm') for f in os.listdir(path))

def is_nifti_file(fname: str) -> bool:
    return fname.lower().endswith(('.nii', '.nii.gz'))

def discover_studies() -> List[dict]:
    discovered = []
    for root in SCAN_ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            # Skip hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            # Detect study by presence of DICOM folder or NIfTI file
            if is_dicom_folder(dirpath) or any(is_nifti_file(f) for f in files):
                study_id = pathlib.Path(dirpath).as_posix()
                discovered.append({"study_path": dirpath, "study_id": study_id})
    return discovered

def register_study(study: dict):
    if PensieveCoreMemory is None:
        print("PensieveCoreMemory not available – registration skipped", study)
        return False
    # The real API would be something like:
    # PensieveCoreMemory.register_study(study_path=study['study_path'])
    print(f"Registering study {study['study_id']}")
    return True

def main():
    studies = discover_studies()
    print(f"Discovered {len(studies)} potential legacy studies")
    for s in studies:
        register_study(s)

if __name__ == "__main__":
    main()
