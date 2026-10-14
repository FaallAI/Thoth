"""Apply the shipped 0010_footage.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    execute_sql_file(__file__)
