"""Projects owned by the control plane (spec 2026-10-18, section 3.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field, field_validator

from thoth_control_plane.domain.models import ProjectId, StrictModel

ProjectName = Annotated[str, Field(min_length=1, max_length=120)]


class Project(StrictModel):
    project_id: ProjectId
    name: ProjectName
    created_at: datetime
    updated_at: datetime


class CreateProject(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]

    @field_validator("name")
    @classmethod
    def _trimmed(cls, name: str) -> str:
        name = name.strip()
        if not 1 <= len(name) <= 120:
            raise ValueError("name must be 1-120 characters after trimming")
        return name


class ProjectList(StrictModel):
    items: list[Project]
