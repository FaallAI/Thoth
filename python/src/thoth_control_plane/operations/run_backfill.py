"""One run row per workflow that already has a source report (spec 2026-10-18, section 3.5).

Idempotent: a workflow with a row is counted `present` and left alone. The rows start `unknown`;
reading them settles the real status from Temporal or marks the history expired.
"""

from __future__ import annotations

import json
import re
from typing import NamedTuple
from urllib.parse import urlsplit

from pydantic import ValidationError

from thoth_control_plane.domain.models import WorkflowSource
from thoth_control_plane.domain.workflow_runs import StoredRun
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore

#: Only workflow folders; candidate (`-c<n>`) and other folders are skipped, not counted.
_WORKFLOW = re.compile(r"^wf_[0-9a-f]{24}$")


class BackfillCounts(NamedTuple):
    inserted: int
    present: int
    invalid: int


def backfill_runs(store: WorkflowRunStore) -> BackfillCounts:
    inserted = present = invalid = 0
    for workflow_id, content, first_seen in store.source_report_rows():
        if not _WORKFLOW.fullmatch(workflow_id):
            continue
        try:
            source = json.loads(content)["source"]
            display_url = urlsplit(source["canonical_url"])._replace(query="", fragment="").geturl()
            checked = WorkflowSource(display_url=display_url, platform=source["platform"])
        except (KeyError, TypeError, ValueError, ValidationError):
            invalid += 1
            continue
        run = StoredRun(
            workflow_id=workflow_id,
            project_id=None,
            actor_type="user",
            actor_id="owner",
            display_url=str(checked.display_url),
            platform=checked.platform,
            status="unknown",
            history_expired=False,
            summary=None,
            created_at=first_seen,
            updated_at=first_seen,
        )
        if store.insert_missing(run):
            inserted += 1
        else:
            present += 1
    return BackfillCounts(inserted, present, invalid)
