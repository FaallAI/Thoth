"""Typed Python activities registered by the control-plane worker."""

from thoth_control_plane.activities.content_assembly import (
    ContentAssemblyActivityInput,
    ContentAssemblyActivityResult,
    assemble_content,
    build_content_assembly_activity,
)
from thoth_control_plane.activities.source_attribution import (
    SourceAttributionActivityInput,
    SourceAttributionActivityResult,
    attribute_source,
    build_source_attribution_activity,
)
from thoth_control_plane.activities.source_investigation import (
    AcquisitionRunner,
    SourceInvestigationActivityInput,
    build_source_investigation_activity,
    inspect_source_candidates,
)

__all__ = [
    "AcquisitionRunner",
    "ContentAssemblyActivityInput",
    "ContentAssemblyActivityResult",
    "SourceAttributionActivityInput",
    "SourceAttributionActivityResult",
    "SourceInvestigationActivityInput",
    "assemble_content",
    "attribute_source",
    "build_content_assembly_activity",
    "build_source_attribution_activity",
    "build_source_investigation_activity",
    "inspect_source_candidates",
]
