"""Apply the shipped 0015_metering.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0015"
down_revision = "0014"


def upgrade() -> None:
    execute_sql_file(__file__)
