"""Apply the shipped 0023_run_listing.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0023"
down_revision = "0022"


def upgrade() -> None:
    execute_sql_file(__file__)
