"""Apply the shipped 0028_style_templates.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0028"
down_revision = "0027"


def upgrade() -> None:
    execute_sql_file(__file__)
