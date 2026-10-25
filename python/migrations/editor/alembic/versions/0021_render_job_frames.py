"""Apply the shipped 0021_render_job_frames.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0021"
down_revision = "0020"


def upgrade() -> None:
    execute_sql_file(__file__)
