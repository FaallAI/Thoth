"""Apply the shipped 0019_workflow_steps.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0019"
down_revision = "0018"


def upgrade() -> None:
    execute_sql_file(__file__)
