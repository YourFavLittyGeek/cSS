"""System readiness evaluation and scientific workflow diagnostics.

Mission ID: PERCIVAL-SETUP-REDESIGN-2026
"""

from typing import Dict, Any, List
from .models import ReadinessCapability, DependencyNode


class SystemReadinessService:
    """Evaluates granular capability readiness and maintains system dependency graphs."""

    @staticmethod
    def evaluate_capabilities(config: Dict[str, Any], discovery_data: Dict[str, Any]) -> Dict[str, Any]:
        """Compute the 7 scientific capabilities from current configuration and validation states."""
        capabilities: Dict[str, ReadinessCapability] = {}

        # Component validation shortcuts
        py_valid = config.get("python_valid", False)
        ws_valid = config.get("workspace_valid", False)
        ws_free = config.get("workspace_free_gb", 0.0)
        pipe_valid = config.get("pipeline_valid", False)
        fs_valid = config.get("freesurfer_valid", False)
        lic_valid = config.get("license_valid", False)
        dcm_valid = config.get("dcm2niix_valid", False)
        vault_valid = config.get("vault_valid", False)
        vault_connected = config.get("vault_connected", False)
        pensieve_valid = config.get("pensieve_valid", True)

        # 1. Capability: can_launch
        c_launch_blockers = []
        if not py_valid: c_launch_blockers.append("Valid Python 3.10+ environment required")
        if not ws_valid: c_launch_blockers.append("Writable Mac SSD workspace directory required")
        c_launch_warnings = []
        if ws_free < 15.0: c_launch_warnings.append(f"Low SSD headroom ({ws_free} GB free; 15+ GB recommended)")

        capabilities["can_launch"] = ReadinessCapability(
            id="can_launch",
            label="Application Launch & UI Navigation",
            ready=len(c_launch_blockers) == 0,
            required_components=["python", "workspace"],
            blockers=c_launch_blockers,
            warnings=c_launch_warnings
        )

        # 2. Capability: can_import
        c_import_blockers = list(c_launch_blockers)
        if not dcm_valid: c_import_blockers.append("dcm2niix executable required for DICOM conversion")
        capabilities["can_import"] = ReadinessCapability(
            id="can_import",
            label="DICOM Study Ingestion & Conversion",
            ready=len(c_import_blockers) == 0,
            required_components=["python", "workspace", "dcm2niix"],
            blockers=c_import_blockers,
            warnings=[]
        )

        # 3. Capability: can_run_albus
        c_albus_blockers = list(c_import_blockers)
        if not pipe_valid: c_albus_blockers.append("PERCIVAL pipeline scripts required")
        capabilities["can_run_albus"] = ReadinessCapability(
            id="can_run_albus",
            label="ALBUS Candidate Detection Engine",
            ready=len(c_albus_blockers) == 0,
            required_components=["python", "pipeline", "dcm2niix"],
            blockers=c_albus_blockers,
            warnings=[]
        )

        # 4. Capability: can_run_pipeline
        c_pipe_blockers = list(c_albus_blockers)
        if not fs_valid: c_pipe_blockers.append("FreeSurfer 7+ installation required (mri_synthseg, mri_convert)")
        if not lic_valid: c_pipe_blockers.append("Valid FreeSurfer license file required")
        capabilities["can_run_pipeline"] = ReadinessCapability(
            id="can_run_pipeline",
            label="Full Neuroimaging Pipeline (SynthSeg & Morph3D)",
            ready=len(c_pipe_blockers) == 0,
            required_components=["python", "pipeline", "freesurfer", "license", "dcm2niix"],
            blockers=c_pipe_blockers,
            warnings=[]
        )

        # 5. Capability: can_review
        capabilities["can_review"] = ReadinessCapability(
            id="can_review",
            label="Interactive Clinician Review & Blind Viewer",
            ready=capabilities["can_launch"].ready,
            required_components=["python", "workspace"],
            blockers=c_launch_blockers,
            warnings=[]
        )

        # 6. Capability: can_save_annotations
        c_annot_blockers = list(c_launch_blockers)
        if not pensieve_valid: c_annot_blockers.append("Pensieve provenance database corrupted or locked")
        capabilities["can_save_annotations"] = ReadinessCapability(
            id="can_save_annotations",
            label="Expert Annotations & Pensieve Ledger",
            ready=len(c_annot_blockers) == 0,
            required_components=["python", "workspace", "pensieve"],
            blockers=c_annot_blockers,
            warnings=[]
        )

        # 7. Capability: can_archive
        c_arch_blockers = []
        c_arch_warnings = []
        if not vault_connected:
            c_arch_warnings.append("External Data Vault is disconnected; cold archival paused")
        elif not vault_valid:
            c_arch_blockers.append("External Data Vault is read-only or invalid")

        capabilities["can_archive"] = ReadinessCapability(
            id="can_archive",
            label="Permanent Cold Vault Archival & Safe Ejection",
            ready=vault_connected and vault_valid,
            required_components=["vault"],
            blockers=c_arch_blockers,
            warnings=c_arch_warnings
        )

        # Overall readiness
        # Required for first launch: can_launch, can_import, can_run_albus, can_review, can_save_annotations
        # FreeSurfer and Vault are required for full autonomous processing and cold storage, but user can complete setup with warnings
        all_required_ready = all(
            capabilities[cid].ready for cid in ["can_launch", "can_import", "can_run_albus", "can_review", "can_save_annotations"]
        )
        full_clinical_ready = all_required_ready and capabilities["can_run_pipeline"].ready and capabilities["can_archive"].ready

        return {
            "ready": all_required_ready,
            "full_clinical_ready": full_clinical_ready,
            "capabilities": {k: v.to_dict() for k, v in capabilities.items()},
            "blockers_count": sum(len(v.blockers) for v in capabilities.values()),
            "warnings_count": sum(len(v.warnings) for v in capabilities.values())
        }

    @staticmethod
    def get_dependency_map() -> List[Dict[str, Any]]:
        """Return the directed dependency graph nodes for System Configuration."""
        nodes = [
            DependencyNode(
                component_id="python",
                label="Python 3.10+ Environment",
                depends_on=[],
                dependents=["pipeline", "albus", "pensieve"]
            ),
            DependencyNode(
                component_id="workspace",
                label="Internal SSD Workspace",
                depends_on=[],
                dependents=["pipeline", "dcm2niix", "pensieve", "studies"]
            ),
            DependencyNode(
                component_id="pipeline",
                label="PERCIVAL Pipeline Scripts",
                depends_on=["python", "workspace"],
                dependents=["albus", "lumos_nox", "full_pipeline"]
            ),
            DependencyNode(
                component_id="freesurfer",
                label="FreeSurfer Suite",
                depends_on=["license"],
                dependents=["full_pipeline", "synthseg"]
            ),
            DependencyNode(
                component_id="license",
                label="FreeSurfer License",
                depends_on=[],
                dependents=["freesurfer"]
            ),
            DependencyNode(
                component_id="dcm2niix",
                label="MRI Tool: dcm2niix",
                depends_on=["workspace"],
                dependents=["import", "full_pipeline"]
            ),
            DependencyNode(
                component_id="vault",
                label="External Data Vault",
                depends_on=[],
                dependents=["archival", "sync_center", "pensieve_backup"]
            ),
            DependencyNode(
                component_id="pensieve",
                label="Pensieve SQLite Ledger",
                depends_on=["python", "workspace"],
                dependents=["expert_review", "annotations", "provenance"]
            )
        ]
        return [n.to_dict() for n in nodes]
