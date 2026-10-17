"""Moving the media already on the volume into the store (spec 2026-10-17)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from thoth_control_plane import cli
from thoth_control_plane.cli import app
from thoth_control_plane.infrastructure.media_store import LocalMediaStore
from thoth_control_plane.operations.media_import import (
    MediaImportCounts,
    MediaRemovalCounts,
    import_media,
    remove_local_media,
)

VIDEO = "reports/wf_a/media/tiktok-1.mp4"
CARD = "reports/wf_a/cards/profile.png"
REPORT = "reports/wf_a/source-report.json"


def _write(root: Path, relative: str, content: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _volume_and_store(tmp_path: Path) -> tuple[Path, LocalMediaStore]:
    volume = tmp_path / "artifacts"
    volume.mkdir()
    store_root = tmp_path / "store"
    store_root.mkdir()
    return volume, LocalMediaStore(store_root)


def test_media_is_imported_and_report_json_is_left_alone(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    _write(volume, CARD, b"png")
    _write(volume, REPORT, b"{}")
    assert import_media(volume, store) == MediaImportCounts(2, 0, 0, 0)
    assert store.stat(VIDEO).size_bytes == 5
    assert store.list("reports/wf_a/") == [CARD, VIDEO]


def test_a_rerun_finds_everything_present(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    import_media(volume, store)
    assert import_media(volume, store) == MediaImportCounts(0, 1, 0, 0)


def test_a_different_object_is_a_mismatch_and_never_overwritten(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"local")
    store.put_file(VIDEO, _write(tmp_path, "other.mp4", b"stored-other"))
    assert import_media(volume, store) == MediaImportCounts(0, 0, 0, 1)
    assert store.stat(VIDEO).size_bytes == len(b"stored-other")


def test_links_partials_and_bad_names_are_invalid(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    _write(volume, "reports/wf_a/footage/half.mp4.part", b"x")
    _write(volume, "reports/wf_a/media/bad name.mp4", b"x")
    outside = _write(tmp_path, "outside/secret.mp4", b"secret")
    try:
        (volume / "reports/wf_a/media/link.mp4").symlink_to(outside)
        (volume / "reports/wf_b").symlink_to(outside.parent, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available here")
    assert import_media(volume, store) == MediaImportCounts(1, 0, 4, 0)
    assert store.list("reports/wf_b/") == []


def test_an_unreadable_file_is_invalid(tmp_path: Path, monkeypatch) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    _write(volume, CARD, b"png")
    from thoth_control_plane.operations import media_import

    real = media_import.sha256_file

    def unreadable(path: Path) -> str:
        if path.name == "profile.png":
            raise PermissionError("denied")
        return real(path)

    monkeypatch.setattr(media_import, "sha256_file", unreadable)
    assert import_media(volume, store) == MediaImportCounts(1, 0, 1, 0)


def test_an_upload_that_fails_its_read_back_is_removed_and_counted(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")

    class Corrupting(LocalMediaStore):
        def fetch(self, location: str, destination: Path) -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"corrupt")

    corrupting = Corrupting(store.root)
    assert import_media(volume, corrupting) == MediaImportCounts(0, 0, 0, 1)
    assert store.list("reports/wf_a/") == []


def test_remove_local_deletes_only_verified_media(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    _write(volume, REPORT, b"{}")
    import_media(volume, store)
    assert remove_local_media(volume, store) == MediaRemovalCounts(removed=1, kept=0)
    assert not (volume / VIDEO).exists()
    assert not (volume / "reports/wf_a/media").exists()  # emptied folders go too
    assert (volume / REPORT).read_bytes() == b"{}"


def test_remove_local_keeps_a_file_whose_object_is_missing_or_different(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    _write(volume, CARD, b"png")
    store.put_file(CARD, _write(tmp_path, "other.png", b"different"))
    assert remove_local_media(volume, store) == MediaRemovalCounts(removed=0, kept=2)
    assert (volume / VIDEO).exists() and (volume / CARD).exists()


def test_remove_local_refuses_a_local_store_on_the_same_root(tmp_path: Path) -> None:
    volume = tmp_path / "artifacts"
    _write(volume, VIDEO, b"video")
    with pytest.raises(ValueError, match="media_store_is_the_volume"):
        remove_local_media(volume, LocalMediaStore(volume))
    assert (volume / VIDEO).exists()


class _CliStore(LocalMediaStore):
    def ensure_bucket(self) -> None:
        return None


def _cli(monkeypatch, store: LocalMediaStore, *args: str):
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    monkeypatch.setenv("THOTH_MEDIA_S3_ENDPOINT", "127.0.0.1:9")
    monkeypatch.setattr(cli.S3MediaStore, "from_settings", classmethod(lambda cls, settings: store))
    return CliRunner().invoke(app, ["media", "import", *args])


def test_cli_prints_counts_only(tmp_path: Path, monkeypatch) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    result = _cli(monkeypatch, _CliStore(store.root), "--artifact-root", str(volume))
    assert result.exit_code == 0
    assert result.output.strip() == "imported=1 present=0 invalid=0 mismatch=0"


def test_cli_exits_one_on_a_mismatch(tmp_path: Path, monkeypatch) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"local")
    store.put_file(VIDEO, _write(tmp_path, "o.mp4", b"other"))
    result = _cli(monkeypatch, _CliStore(store.root), "--artifact-root", str(volume))
    assert result.exit_code == 1
    assert result.output.strip().endswith("mismatch=1")


def test_cli_remove_local_prints_its_counts(tmp_path: Path, monkeypatch) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")
    import_media(volume, store)
    result = _cli(
        monkeypatch, _CliStore(store.root), "--artifact-root", str(volume), "--remove-local"
    )
    assert result.exit_code == 0
    assert result.output.strip() == "removed=1 kept=0"


def test_cli_refuses_without_an_s3_endpoint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    monkeypatch.delenv("THOTH_MEDIA_S3_ENDPOINT", raising=False)
    result = CliRunner().invoke(app, ["media", "import", "--artifact-root", str(tmp_path)])
    assert result.exit_code == 1
    assert result.output.strip() == "media store is not configured"


@pytest.mark.parametrize("store_root", ["artifacts/store", "."])
def test_remove_local_refuses_a_local_store_nested_with_the_volume(
    tmp_path: Path, store_root: str
) -> None:
    volume = tmp_path / "artifacts"
    _write(volume, VIDEO, b"video")
    (tmp_path / store_root).mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="media_store_is_the_volume"):
        remove_local_media(volume, LocalMediaStore(tmp_path / store_root))
    assert (volume / VIDEO).exists()


def test_cli_refuses_an_endpoint_without_keys_in_one_line(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("THOTH_CONTROL_PLANE_API_KEY", "k")
    monkeypatch.setenv("THOTH_MEDIA_S3_ENDPOINT", "127.0.0.1:9")
    monkeypatch.delenv("THOTH_MEDIA_S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("THOTH_MEDIA_S3_SECRET_KEY", raising=False)
    result = CliRunner().invoke(app, ["media", "import", "--artifact-root", str(tmp_path)])
    assert result.exit_code == 1
    assert result.output.strip() == "media store is not configured"
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_cli_reports_a_local_disk_failure_in_one_line(tmp_path: Path, monkeypatch) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, VIDEO, b"video")

    def full_disk(root: Path, target, **_: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cli, "import_media", full_disk)
    result = _cli(monkeypatch, _CliStore(store.root), "--artifact-root", str(volume))
    assert result.exit_code == 1
    assert result.output.strip() == "media import failed: local disk error"
    assert isinstance(result.exception, SystemExit)


def test_archive_copies_report_json_and_legacy_scout_under_archive(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, REPORT, b"{}")
    _write(volume, "legacy-scout/wf_a/source-report.json", b'{"l":1}')
    assert import_media(volume, store, archive=True) == MediaImportCounts(2, 0, 0, 0)
    assert store.list("archive/reports/") == ["archive/reports/wf_a/source-report.json"]
    assert store.list("archive/legacy-scout/") == ["archive/legacy-scout/wf_a/source-report.json"]
    assert import_media(volume, store, archive=True) == MediaImportCounts(0, 2, 0, 0)


def test_archive_remove_local_keeps_nothing_it_verified(tmp_path: Path) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, REPORT, b"{}")
    _write(volume, "legacy-scout/wf_a/source-report.json", b'{"l":1}')
    import_media(volume, store, archive=True)
    assert remove_local_media(volume, store, archive=True) == MediaRemovalCounts(2, 0)
    assert not (volume / "reports").exists() or not any((volume / "reports").rglob("*"))


def test_cli_archive_prints_counts(tmp_path: Path, monkeypatch) -> None:
    volume, store = _volume_and_store(tmp_path)
    _write(volume, REPORT, b"{}")
    result = _cli(monkeypatch, _CliStore(store.root), "--artifact-root", str(volume), "--archive")
    assert result.exit_code == 0
    assert result.output.strip() == "imported=1 present=0 invalid=0 mismatch=0"
