from pathlib import Path

from typer.testing import CliRunner

from thoth_control_plane.cli import app
from thoth_control_plane.infrastructure.report_store import ReportStore, ReportStoreUnavailable
from thoth_control_plane.operations.report_import import ImportCounts, import_reports


def _write(root: Path, relative: str, content: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_imports_the_four_report_names_with_their_kinds(tmp_path, report_store) -> None:
    _write(tmp_path, "reports/wf_a/source-report.json", b'{"a": 1}')
    _write(tmp_path, "reports/wf_a/source-attribution.json", b'{"b": 1}')
    _write(tmp_path, "reports/wf_a/content-set.json", b'{"c": 1}')
    _write(tmp_path, "reports/wf_a-c1/source-report.json", b'{"d": 1}')
    _write(tmp_path, "legacy-scout/wf_b/source-report.json", b'{"e": 1}')

    assert import_reports(tmp_path, report_store) == ImportCounts(imported=5, present=0, invalid=0)
    assert report_store.get("reports/wf_a-c1/source-report.json") == b'{"d": 1}'


def test_a_rerun_imports_nothing_and_never_overwrites(tmp_path, report_store) -> None:
    _write(tmp_path, "reports/wf_a/source-report.json", b'{"a": 1}')
    import_reports(tmp_path, report_store)
    report_store.put("reports/wf_a/source-report.json", "source_report", b'{"newer": 1}')

    assert import_reports(tmp_path, report_store) == ImportCounts(imported=0, present=1, invalid=0)
    assert report_store.get("reports/wf_a/source-report.json") == b'{"newer": 1}'


def test_invalid_json_is_counted_and_the_rest_imported(tmp_path, report_store) -> None:
    _write(tmp_path, "reports/wf_a/source-report.json", b"not json")
    _write(tmp_path, "reports/wf_b/source-report.json", b'{"ok": 1}')
    assert import_reports(tmp_path, report_store) == ImportCounts(imported=1, present=0, invalid=1)


def test_other_files_and_links_are_ignored(tmp_path, report_store) -> None:
    _write(tmp_path, "reports/wf_a/media/clip.json", b"{}")
    _write(tmp_path, "reports/wf_a/footage/x.json", b"{}")
    _write(tmp_path, "renders/r1/metadata.json", b"{}")
    outside = tmp_path.parent / "outside.json"
    outside.write_bytes(b'{"secret": 1}')
    (tmp_path / "reports" / "wf_link").mkdir(parents=True)
    (tmp_path / "reports" / "wf_link" / "source-report.json").symlink_to(outside)

    assert import_reports(tmp_path, report_store) == ImportCounts(imported=0, present=0, invalid=0)


def test_a_linked_folder_is_skipped(tmp_path, report_store) -> None:
    elsewhere = tmp_path / "elsewhere"
    _write(elsewhere, "source-report.json", b'{"a": 1}')
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "wf_dir").symlink_to(elsewhere, target_is_directory=True)

    assert import_reports(tmp_path, report_store) == ImportCounts(imported=0, present=0, invalid=0)


def _cli(monkeypatch, store, root: Path):
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "test-key")
    monkeypatch.setenv("THOTH_EDITOR_DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setattr(ReportStore, "connect", classmethod(lambda cls, url: store))
    return CliRunner().invoke(app, ["reports", "import", "--artifact-root", str(root)])


def test_cli_prints_counts_only(tmp_path, report_store, monkeypatch) -> None:
    _write(tmp_path, "reports/wf_a/source-report.json", b'{"a": 1}')
    result = _cli(monkeypatch, report_store, tmp_path)
    assert result.exit_code == 0
    assert result.output.strip() == "imported=1 present=0 invalid=0"


def test_cli_exits_one_when_a_report_is_invalid(tmp_path, report_store, monkeypatch) -> None:
    _write(tmp_path, "reports/wf_a/source-report.json", b"nope")
    result = _cli(monkeypatch, report_store, tmp_path)
    assert result.exit_code == 1
    assert "invalid=1" in result.output
    assert "wf_a" not in result.output


def test_cli_stops_when_the_store_is_unavailable(tmp_path, monkeypatch) -> None:
    class Down:
        def insert_missing(self, *args) -> bool:
            raise ReportStoreUnavailable("report_store_unavailable")

    _write(tmp_path, "reports/wf_a/source-report.json", b'{"a": 1}')
    result = _cli(monkeypatch, Down(), tmp_path)
    assert result.exit_code == 1
    assert "report store unavailable" in result.output
