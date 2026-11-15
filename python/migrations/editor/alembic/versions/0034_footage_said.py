"""Apply the shipped 0034_footage_said.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0034"
down_revision = "0033"


def upgrade() -> None:
    execute_sql_file(__file__)
