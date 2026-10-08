"""Apply the shipped 0008_source_accounts.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    execute_sql_file(__file__)
