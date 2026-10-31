"""Apply the shipped 0027_narration.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0027"
down_revision = "0026"


def upgrade() -> None:
    execute_sql_file(__file__)
