"""Sanitized global diagnostic report exporter for PERCIVAL.

Mission ID: PERCIVAL-SETUP-REDESIGN-2026
"""

import os
import json
import time
import datetime
from typing import Dict, Any


class DiagnosticExportService:
    """Produces sanitized, comprehensive diagnostic exports without exposing credentials or patient data."""

    @staticmethod
    def generate_report(state_mgr, discovery_svc, readiness_svc) -> Dict[str, Any]:
        """Compile a complete sanitized diagnostic dictionary."""
        state = state_mgr.get_state()
        discovery = discovery_svc.run_full_discovery()
        validated_cfg = state.get("validated_config", {})
        readiness = readiness_svc.evaluate_capabilities(validated_cfg, discovery)

        # Build sanitized report
        report = {
            "meta": {
                "generated_at": datetime.datetime.now().isoformat(),
                "application": "PERCIVAL — Cerebral Superficial Siderosis Detection",
                "app_version": state.get("app_version", "v5.26"),
                "setup_state": state.get("state", "UNKNOWN"),
                "is_first_launch": state.get("is_first_launch", False),
                "completed": state.get("completed", False),
                "completed_at": state.get("completed_at")
            },
            "host_system": discovery.get("system", {}),
            "python_environment": {
                "active_executable": validated_cfg.get("python_executable", "auto"),
                "version": validated_cfg.get("python_version", "unknown"),
                "candidates_count": len(discovery.get("python", []))
            },
            "pipeline": {
                "path": validated_cfg.get("pipeline_dir", "auto"),
                "version": validated_cfg.get("pipeline_version", "unknown"),
                "build": validated_cfg.get("pipeline_build", "unknown")
            },
            "freesurfer": {
                "home": validated_cfg.get("freesurfer_home", "none"),
                "version": validated_cfg.get("freesurfer_version", "unknown"),
                "license_path": validated_cfg.get("fs_license", "none"),
                "license_structure_valid": validated_cfg.get("license_valid", False)
                # NOTE: License contents are strictly omitted for security
            },
            "mri_tools": {
                "dcm2niix": validated_cfg.get("dcm2niix_path", "none"),
                "dcm2niix_version": validated_cfg.get("dcm2niix_version", "unknown")
            },
            "storage_topology": {
                "workspace_path": validated_cfg.get("workspace_dir", state_mgr.workspace_root),
                "workspace_free_gb": validated_cfg.get("workspace_free_gb", 0.0),
                "vault_path": validated_cfg.get("vault_mount", "none"),
                "vault_uuid": validated_cfg.get("vault_uuid", "none"),
                "vault_free_gb": validated_cfg.get("vault_free_gb", 0.0)
            },
            "pensieve": {
                "database_path": validated_cfg.get("pensieve_db_path", "none"),
                "integrity_ok": validated_cfg.get("pensieve_valid", True),
                "table_count": validated_cfg.get("pensieve_tables_count", 0),
                "studies_count": validated_cfg.get("pensieve_studies_count", 0)
            },
            "readiness": readiness,
            "dependency_graph": readiness_svc.get_dependency_map()
        }
        return report

    @staticmethod
    def format_markdown(report_dict: Dict[str, Any]) -> str:
        """Render diagnostic report into readable GitHub-flavored Markdown."""
        meta = report_dict["meta"]
        sys_inf = report_dict["host_system"]
        py_inf = report_dict["python_environment"]
        pipe = report_dict["pipeline"]
        fs = report_dict["freesurfer"]
        st = report_dict["storage_topology"]
        read = report_dict["readiness"]

        lines = [
            f"# PERCIVAL System Diagnostic Report",
            f"**Generated:** {meta['generated_at']}  ",
            f"**Application Version:** {meta['app_version']}  ",
            f"**Setup State:** `{meta['setup_state']}` (Completed: {meta['completed']})  ",
            "",
            "## 1. Host System",
            f"- **OS:** {sys_inf.get('os_name')} {sys_inf.get('os_version')} ({sys_inf.get('architecture')})",
            f"- **Processor:** {sys_inf.get('cpu_brand')}",
            f"- **RAM:** {sys_inf.get('total_ram_gb')} GB total",
            f"- **Disk:** {sys_inf.get('free_ssd_gb')} GB free / {sys_inf.get('total_ssd_gb')} GB total",
            "",
            "## 2. Scientific Software & Pipeline",
            f"- **Python:** `{py_inf.get('active_executable')}` ({py_inf.get('version')})",
            f"- **Pipeline:** `{pipe.get('path')}` ({pipe.get('version')} · {pipe.get('build')})",
            f"- **FreeSurfer:** `{fs.get('home')}` ({fs.get('version')})",
            f"- **License Path:** `{fs.get('license_path')}` (Valid: {fs.get('license_structure_valid')})",
            f"- **dcm2niix:** `{report_dict['mri_tools'].get('dcm2niix')}`",
            "",
            "## 3. Storage Topology & Vault",
            f"- **Internal SSD Workspace:** `{st.get('workspace_path')}` ({st.get('workspace_free_gb')} GB free)",
            f"- **External HDD Vault:** `{st.get('vault_path')}` (UUID: {st.get('vault_uuid')}, {st.get('vault_free_gb')} GB free)",
            "",
            "## 4. Capability Readiness",
            f"- **Overall Ready for Processing:** `{read.get('ready')}`",
            f"- **Full Autonomous Processing:** `{read.get('full_clinical_ready')}`",
            f"- **Active Blockers:** {read.get('blockers_count')}",
            f"- **Warnings:** {read.get('warnings_count')}",
            ""
        ]

        caps = read.get("capabilities", {})
        lines.append("### Granular Capabilities")
        for cid, cap in caps.items():
            status = "READY" if cap["ready"] else "BLOCKED"
            lines.append(f"- **{cap['label']}**: `{status}`")
            if cap["blockers"]:
                for b in cap["blockers"]:
                    lines.append(f"  - ❌ Blocked: {b}")
            if cap["warnings"]:
                for w in cap["warnings"]:
                    lines.append(f"  - ⚠️ Warning: {w}")

        return "\n".join(lines)
