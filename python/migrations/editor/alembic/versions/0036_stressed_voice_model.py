"""Apply the shipped 0036_stressed_voice_model.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0036"
down_revision = "0035"


def upgrade() -> None:
    execute_sql_file(__file__)
