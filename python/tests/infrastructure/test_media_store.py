"""The media store contract (spec 2026-10-17); every store implementation passes the same tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from thoth_control_plane.config import Settings
from thoth_control_plane.infrastructure.media_store import (
    LocalMediaStore,
    MediaLocatorInvalid,
    MediaStoreUnavailable,
    MediaUnavailable,
    build_media_store,
    sha256_file,
)

LOCATION = "reports/wf_a/media/tiktok-1.mp4"
STORES = ["local"]


@pytest.fixture(params=STORES)
def store(request: pytest.FixtureRequest, tmp_path: Path):
    root = tmp_path / "store"
    root.mkdir()
    return LocalMediaStore(root)


def _file(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_a_put_file_is_fetched_back_byte_for_byte(store, tmp_path: Path) -> None:
    source = _file(tmp_path, "in.mp4", b"video-bytes" * 100)
    store.put_file(LOCATION, source)
    target = tmp_path / "out" / "copy.mp4"
    store.fetch(LOCATION, target)
    assert target.read_bytes() == source.read_bytes()


def test_stat_reports_size_and_sha256(store, tmp_path: Path) -> None:
    source = _file(tmp_path, "in.png", b"png" * 7)
    store.put_file("reports/wf_a/cards/profile.png", source)
    stat = store.stat("reports/wf_a/cards/profile.png")
    assert stat.size_bytes == 21
    assert stat.sha256 == sha256_file(source)


def test_a_second_put_replaces_the_object(store, tmp_path: Path) -> None:
    store.put_file(LOCATION, _file(tmp_path, "a.mp4", b"first"))
    store.put_file(LOCATION, _file(tmp_path, "b.mp4", b"second!"))
    assert store.stat(LOCATION).size_bytes == 7


def test_an_absent_object_is_unavailable(store, tmp_path: Path) -> None:
    with pytest.raises(MediaUnavailable):
        store.fetch(LOCATION, tmp_path / "x.mp4")
    with pytest.raises(MediaUnavailable):
        store.stat(LOCATION)
    assert not (tmp_path / "x.mp4").exists()


def test_deleting_twice_is_fine(store, tmp_path: Path) -> None:
    store.put_file(LOCATION, _file(tmp_path, "a.mp4", b"x"))
    store.delete(LOCATION)
    store.delete(LOCATION)
    with pytest.raises(MediaUnavailable):
        store.stat(LOCATION)


def test_list_returns_the_locators_below_a_prefix(store, tmp_path: Path) -> None:
    source = _file(tmp_path, "a.mp4", b"x")
    for location in (
        "reports/wf_a/footage/b.mp4",
        "reports/wf_a/footage/a.mp4",
        "reports/wf_a/media/m.mp4",
        "reports/wf_b/footage/c.mp4",
    ):
        store.put_file(location, source)
    assert store.list("reports/wf_a/footage/") == [
        "reports/wf_a/footage/a.mp4",
        "reports/wf_a/footage/b.mp4",
    ]
    assert store.list("reports/wf_none/footage/") == []


@pytest.mark.parametrize(
    "location",
    [
        "",
        "/reports/wf_a/x.mp4",
        "reports/../x.mp4",
        "reports/wf_a/..",
        "reports\\wf_a\\x.mp4",
        "reports/wf_a/c:x.mp4",
        "reports//x.mp4",
        "reports/.hidden/x.mp4",
        "media/wf_a/x.mp4",
        "reports",
        "reports/" + "a" * 600,
    ],
)
def test_an_unsafe_locator_is_refused_before_any_io(store, tmp_path: Path, location: str) -> None:
    source = _file(tmp_path, "a.mp4", b"x")
    for call in (
        lambda: store.put_file(location, source),
        lambda: store.fetch(location, tmp_path / "y.mp4"),
        lambda: store.stat(location),
        lambda: store.delete(location),
    ):
        with pytest.raises(MediaLocatorInvalid):
            call()


def test_the_local_store_refuses_a_link_out_of_its_root(tmp_path: Path) -> None:
    root = tmp_path / "store"
    (root / "reports").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.mp4").write_bytes(b"secret")
    try:
        (root / "reports" / "wf_a").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available here")
    store = LocalMediaStore(root)
    with pytest.raises(MediaLocatorInvalid):
        store.fetch("reports/wf_a/secret.mp4", tmp_path / "copy.mp4")


def test_the_local_store_check_needs_its_root(tmp_path: Path) -> None:
    LocalMediaStore(tmp_path).check()
    with pytest.raises(MediaStoreUnavailable):
        LocalMediaStore(tmp_path / "absent").check()


def test_without_an_endpoint_the_store_is_local_on_the_artifact_root(tmp_path: Path) -> None:
    store = build_media_store(
        Settings(THOTH_CONTROL_PLANE_API_KEY="k", THOTH_CONTROL_PLANE_ARTIFACT_ROOT=tmp_path)
    )
    assert isinstance(store, LocalMediaStore)
    assert store.root == tmp_path.resolve()
