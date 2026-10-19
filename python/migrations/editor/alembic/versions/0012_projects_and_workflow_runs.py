"""Apply the shipped 0012_projects_and_workflow_runs.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    execute_sql_file(__file__)
