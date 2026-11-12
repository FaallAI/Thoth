"""Apply the shipped 0030_narration_previous.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0030"
down_revision = "0029"


def upgrade() -> None:
    execute_sql_file(__file__)
