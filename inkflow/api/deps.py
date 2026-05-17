"""Shared API dependencies — single source of truth for common patterns."""

from inkflow.projects.manager import ProjectManager
from inkflow.memory.world_state import WorldState

# Module-level singleton — avoids repeated mkdir syscalls on every request
_pm = ProjectManager()


def get_ws(project_id: str = "default") -> WorldState:
    """Get WorldState for a project, auto-creating default if needed."""
    try:
        return _pm.get_world_state(project_id)
    except FileNotFoundError:
        if project_id == "default":
            _pm.get_or_create_default()
            return _pm.get_world_state(project_id)
        raise


def save_ws(project_id: str, ws: WorldState):
    """Save WorldState for a project."""
    _pm.save_world_state(project_id, ws)
