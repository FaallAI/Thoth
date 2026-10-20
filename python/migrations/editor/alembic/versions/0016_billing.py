"""Apply the shipped 0016_billing.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0016"
down_revision = "0015"


def upgrade() -> None:
    execute_sql_file(__file__)
