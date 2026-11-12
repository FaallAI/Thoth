"""Apply the shipped 0031_workspace_assets.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0031"
down_revision = "0030"


def upgrade() -> None:
    execute_sql_file(__file__)
