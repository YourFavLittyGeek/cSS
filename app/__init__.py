# Package initializer for Percival GUI

"""Initialize the Percival application package.

This file ensures that the core services are instantiated at import time
so that frontend components (e.g., the File Manager) can call them without
running into "Not Loaded" errors.

We import the FileManager singleton and create a global instance that
other modules can reuse.  The instance is stored in the module-global
variable ``FILE_MANAGER``.
"""

import os
from uengine.file_manager import FileManager

# Base directory – the same logic used in ``css_app.py``
BASE_DIR = os.getenv("CSS_BASE", os.path.expanduser("~/css_project"))
# Attempt to read the vault mount from the settings (if already set)
# Settings are stored in ``app_data/settings.json`` under the base dir.
SETTINGS_PATH = os.path.join(BASE_DIR, "app_data", "settings.json")
vault_mount = None
if os.path.exists(SETTINGS_PATH):
    try:
        import json
        with open(SETTINGS_PATH) as f:
            settings = json.load(f)
        vault_mount = settings.get("vault_mount")
    except Exception:
        vault_mount = None

# Create the singleton FileManager instance
FILE_MANAGER = FileManager(BASE_DIR, vault_root=vault_mount)

def get_file_manager() -> FileManager:
    """Return the globally‑initialized ``FileManager``.
    Other parts of the code base can ``from app import get_file_manager``
    and avoid recreating the object on every request.
    """
    return FILE_MANAGER
