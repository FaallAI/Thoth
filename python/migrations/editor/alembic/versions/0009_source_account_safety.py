"""Apply the shipped 0009_source_account_safety.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    execute_sql_file(__file__)
