"""Apply the shipped 0022_user_locale.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0022"
down_revision = "0021"


def upgrade() -> None:
    execute_sql_file(__file__)
