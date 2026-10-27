"""Apply the shipped 0020_workflow_run_acknowledged.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0020"
down_revision = "0019"


def upgrade() -> None:
    execute_sql_file(__file__)
