"""Apply the shipped 0018_footage_creator.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0018"
down_revision = "0017"


def upgrade() -> None:
    execute_sql_file(__file__)
