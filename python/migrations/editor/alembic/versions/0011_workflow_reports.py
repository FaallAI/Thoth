"""Apply the shipped 0011_workflow_reports.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    execute_sql_file(__file__)
