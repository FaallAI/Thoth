"""Apply the shipped 0033_footage_library.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0033"
down_revision = "0032"


def upgrade() -> None:
    execute_sql_file(__file__)
