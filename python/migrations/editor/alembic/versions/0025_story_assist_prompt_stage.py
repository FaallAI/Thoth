"""Apply the shipped 0025_story_assist_prompt_stage.sql verbatim."""

from thoth_control_plane.operations.editor_migrations import execute_sql_file

revision = "0025"
down_revision = "0024"


def upgrade() -> None:
    execute_sql_file(__file__)
