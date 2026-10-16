"""One-time import of existing report files into PostgreSQL (never overwrites, never deletes)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from thoth_control_plane.activities.content_assembly import ORIGINAL_LOCATION
from thoth_control_plane.infrastructure.report_store import ReportInvalid, ReportStore

_PATTERNS = (
    "reports/*/source-report.json",
    "reports/*/source-attribution.json",
    "reports/*/content-set.json",
    "legacy-scout/*/source-report.json",
)
_KINDS = {"source-attribution.json": "source_attribution", "content-set.json": "content_set"}


@dataclass(frozen=True)
class ImportCounts:
    imported: int
    present: int
    invalid: int


def import_reports(root: Path, store: ReportStore) -> ImportCounts:
    """Insert each candidate report that is not stored yet. `ReportStoreUnavailable` propagates."""
    resolved_root = root.resolve()
    imported = present = invalid = 0
    for pattern in _PATTERNS:
        for path in sorted(root.glob(pattern)):
            if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
                continue
            if not path.resolve().is_relative_to(resolved_root):
                continue
            location = path.relative_to(root).as_posix()
            kind = _KINDS.get(path.name) or (
                "original_source_report"
                if ORIGINAL_LOCATION.fullmatch(location)
                else "source_report"
            )
            try:
                inserted = store.insert_missing(location, kind, path.read_bytes())
            except ReportInvalid:
                invalid += 1
                continue
            if inserted:
                imported += 1
            else:
                present += 1
    return ImportCounts(imported, present, invalid)
