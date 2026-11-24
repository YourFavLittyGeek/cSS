"""legacy_guard.py - retirement support for the pre-architecture layers (Stage 1 of the consolidation; docs/engineering/DEPRECATIONS.md).

The legacy ALBUS / NOX / LUMOS / CORE engines, the old Shadow Lab and governance.py were written against a global legacy sqlite PENSIEVE
(`uengine.pensieve.get_pensieve()`) and an external Data Vault (`uengine.vault.get_vault()`). PENSIEVE is now the derived, per-project
index (`uengine.pensieve_index`), and nothing in the comparison / demonstration paths may write project memory or touch the external
Vault. These null objects let the retained code run read-only:

  NullPensieve  every write is a no-op, every read is empty
  NullVault     never connected (no external path is ever resolved)

RETIRED lists the retired items; the GUI (PERCIVAL > System) and tests read it.
"""


class NullPensieve:
    """drop-in stand-in for uengine.pensieve.PensieveCoreMemory: records nothing, remembers nothing"""
    retired = True

    def __getattr__(self, name):
        if name.startswith("ask_"): return lambda *a, **k: {}
        if name.startswith("get_all") or name.startswith("get_training"): return lambda *a, **k: []
        if name.startswith("get_"): return lambda *a, **k: None
        return lambda *a, **k: None                    # remember_* / record_* / update_*: no-op

    @staticmethod
    def compute_candidate_uid(study_id, hemi, centroid_vox):
        from .pensieve import PensieveCoreMemory
        return PensieveCoreMemory.compute_candidate_uid(study_id, hemi, centroid_vox)


class NullVault:
    """stand-in for uengine.vault.PercivalDataVault: never connected, so retained code never reads or writes the external Vault"""
    root_path = None
    retired = True

    def is_connected(self): return False
    def path(self, *a): raise PermissionError("the external Data Vault is not used by this code path (retired)")
    def get_storage_stats(self): return dict(connected=False)


RETIRED = [
    dict(item="uScore separate scorer (train / freeze / score / held-out evaluation, app screen)", module="unified_score/uscore (model part), app/unified_gui.py",
         replacement="PERCIVAL Decision Engine (uengine/percival/meta.py); x1-x5 extractors stay as NOX inputs", state="retired: refuses"),
    dict(item="Shadow Lab fixed trials + governance.py promotion", module="uengine/shadow_lab.py, uengine/governance.py",
         replacement="SHADOW (uengine/shadow_governed.py) + component registry", state="demonstration only; promotion refuses"),
    dict(item="CORE fixed-weight engine", module="uengine/percival_core.py", replacement="kept as labelled comparison baseline",
         state="comparison only, off by default"),
    dict(item="legacy ALBUS / NOX engines, LUMOS Vault loader", module="uengine/albus.py, uengine/nox.py, uengine/lumos.py (_load_active_checkpoint)",
         replacement="real detector measurements via the CORE adapter; LUMOS.from_percival_model", state="adapter only; no memory / Vault access"),
    dict(item="legacy PENSIEVE sqlite writers and GUI tiles", module="uengine/pensieve.py (writers), /api/percival/pensieve, pensieve_query",
         replacement="uengine/pensieve_index.py", state="routes retired; module kept for its tests"),
    dict(item="older prototypes", module="uengine/shadow.py (Stage-1 engine), uengine/synthetic.py image model, uengine/unified_fusion.py, scripts/train_ranker.py, scripts/classify_surface_patches.py",
         replacement="PERCIVAL Decision Engine", state="kept behind research guards until nothing reads them"),
    dict(item="frozen app bundles committed in the repository", module="app/mac/cSS Pipeline.app, docs/gui_v514/rc*/dist",
         replacement="install.sh / tools/build_percival_dev_app.sh from the current tree", state="removed from the tree (in git history)"),
]
