"""Firebase deployment entry point."""

from pathlib import Path
import json
from job_application_agents.retirement import configured_project, require_active

_project = configured_project()
if not _project:
    _rc = Path(__file__).with_name(".firebaserc")
    if _rc.exists():
        _project = json.loads(_rc.read_text()).get("projects", {}).get("default")
require_active(_project)

from functions.main import *  # noqa: F401,F403
