"""Apply the shipped 0014_project_workspaces.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    execute_sql_file(__file__)
