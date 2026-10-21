"""Apply the shipped 0017_studio_import_decision_reason.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0017"
down_revision = "0016"


def upgrade() -> None:
    execute_sql_file(__file__)
