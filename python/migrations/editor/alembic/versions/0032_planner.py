"""Apply the shipped 0032_planner.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0032"
down_revision = "0031"


def upgrade() -> None:
    execute_sql_file(__file__)
