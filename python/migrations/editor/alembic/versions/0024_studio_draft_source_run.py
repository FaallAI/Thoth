"""Apply the shipped 0024_studio_draft_source_run.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0024"
down_revision = "0023"


def upgrade() -> None:
    execute_sql_file(__file__)
