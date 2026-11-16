"""Apply the shipped 0035_footage_relation.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0035"
down_revision = "0034"


def upgrade() -> None:
    execute_sql_file(__file__)
