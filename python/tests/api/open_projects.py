"""For API fixtures that predate workspaces: every project exists in the bootstrap workspace."""

from thoth_control_plane.auth.models import BOOTSTRAP_WORKSPACE_ID


class OpenProjects:
    def get(self, project_id: str, workspace_id: str) -> object | None:
        return object() if workspace_id == BOOTSTRAP_WORKSPACE_ID else None


OPEN_PROJECTS = OpenProjects()
