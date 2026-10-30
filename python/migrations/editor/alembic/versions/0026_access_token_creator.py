"""Apply the shipped 0026_access_token_creator.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0026"
down_revision = "0025"


def upgrade() -> None:
    execute_sql_file(__file__)
