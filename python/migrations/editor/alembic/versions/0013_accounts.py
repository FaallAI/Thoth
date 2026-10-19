"""Apply the shipped 0013_accounts.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    execute_sql_file(__file__)
