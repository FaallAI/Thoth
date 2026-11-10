"""Apply the shipped 0029_style_script_stage.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0029"
down_revision = "0028"


def upgrade() -> None:
    execute_sql_file(__file__)
