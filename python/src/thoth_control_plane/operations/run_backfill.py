"""One run row per workflow that already has a source report (spec 2026-10-18, section 3.5).

Idempotent: a workflow with a row is counted `present` and left alone. The rows start `unknown`;
reading them settles the real status from Temporal or marks the history expired.

A row's time is the workflow's Temporal start time when Temporal still holds it. The reports were
imported into PostgreSQL on 2026-10-16, so their own timestamps are the import day, not the run;
they are only the fallback for a workflow past Temporal's retention.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, NamedTuple
from urllib.parse import urlsplit

from pydantic import ValidationError
from temporalio.service import RPCError

from thoth_control_plane.domain.models import WorkflowSource
from thoth_control_plane.domain.workflow_runs import StoredRun
from thoth_control_plane.infrastructure.workflow_run_store import WorkflowRunStore

#: Only workflow folders; candidate (`-c<n>`) and other folders are skipped, not counted.
_WORKFLOW = re.compile(r"^wf_[0-9a-f]{24}$")

logger = logging.getLogger(__name__)


class BackfillCounts(NamedTuple):
    inserted: int
    present: int
    invalid: int


def is_workflow_id(value: str) -> bool:
    return _WORKFLOW.fullmatch(value) is not None


async def temporal_start_times(client: Any, workflow_ids: Iterable[str]) -> dict[str, datetime]:
    """Start times Temporal still holds; a workflow past retention (or any error) is skipped."""
    found: dict[str, datetime] = {}
    for workflow_id in workflow_ids:
        try:
            found[workflow_id] = (await client.get_workflow_handle(workflow_id).describe()).start_time
        except RPCError as error:
            logger.debug("no start time workflow_id=%s reason=%s", workflow_id, error.status)
    return found


def backfill_runs(
    store: WorkflowRunStore, start_times: Mapping[str, datetime] | None = None
) -> BackfillCounts:
    inserted = present = invalid = 0
    for workflow_id, content, first_seen in store.source_report_rows():
        if not is_workflow_id(workflow_id):
            continue
        when = (start_times or {}).get(workflow_id, first_seen)
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
            created_at=when,
            updated_at=when,
        )
        if store.insert_missing(run):
            inserted += 1
        else:
            present += 1
    return BackfillCounts(inserted, present, invalid)
