"""Filesystem containment tests for the one E1 artifact path authority."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from thoth_control_plane.application.editor_asset_ports import EditorAssetUploadTooLarge
from thoth_control_plane.application.render_job_ports import (
    ArtifactPathInvalid,
    ArtifactUnavailable,
    RenderOutputTooLarge,
)
from thoth_control_plane.domain.render_jobs import RenderOutputFacts
from thoth_control_plane.infrastructure.artifact_root import LocalArtifactRoot

JOB = "rj_1"
OTHER_JOB = "rj_2"
UNSAFE_IDS = [
    "../job",
    "..",
    "/tmp/job",
    "C:\\job",
    "file:x",
    "job/../../escape",
    "job\\nested",
    "job id",
    "",
    "_leading",
    "a" * 129,
]


def checksum_of(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def facts(payload: bytes, **overrides: object) -> RenderOutputFacts:
    values: dict[str, object] = {
        "media_type": "video/mp4",
        "size_bytes": len(payload),
        "checksum": checksum_of(payload),
        "codec": "h264",
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "duration_seconds": 20.0,
        "has_audio": True,
    }
    values.update(overrides)
    return RenderOutputFacts.model_validate(values)


# --- identity containment -------------------------------------------------


@pytest.mark.parametrize("unsafe", UNSAFE_IDS)
def test_job_identity_never_escapes_root(tmp_path: Path, unsafe: str) -> None:
    with pytest.raises(ArtifactPathInvalid):
        LocalArtifactRoot(tmp_path).prepare(unsafe)


@pytest.mark.parametrize("unsafe", UNSAFE_IDS)
def test_every_entry_point_validates_job_identity(tmp_path: Path, unsafe: str) -> None:
    root = LocalArtifactRoot(tmp_path)
    expected = facts(b"payload")
    with pytest.raises(ArtifactPathInvalid):
        root.verify_temporary_output(unsafe, expected)
    with pytest.raises(ArtifactPathInvalid):
        root.publish(unsafe, expected, b"{}", b"{}")
    with pytest.raises(ArtifactPathInvalid):
        root.resolve_download(unsafe, "renders/rj_1/output.mp4")
    with pytest.raises(ArtifactPathInvalid):
        root.read_bundle(unsafe)
    with pytest.raises(ArtifactPathInvalid):
        root.cleanup(unsafe)


# --- uploads ---------------------------------------------------------------


async def chunks_of(*parts: bytes):
    for part in parts:
        yield part


async def disconnecting():
    yield b"\x89PNG\r\n\x1a\n"
    raise ConnectionResetError("client went away")


def leftovers(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


@pytest.mark.asyncio
async def test_receive_upload_streams_hashes_and_keeps_the_head(tmp_path: Path) -> None:
    received = await LocalArtifactRoot(tmp_path).receive_upload(
        asset_id="asset_1", chunks=chunks_of(b"\x89PNG", b"\r\n\x1a\n", b"rest"), max_bytes=64
    )

    assert received.size_bytes == 12
    assert received.checksum == checksum_of(b"\x89PNG\r\n\x1a\nrest")
    assert received.head.startswith(b"\x89PNG\r\n\x1a\n")
    assert received.location == "temp/uploads/asset_1.part"
    assert received.path.read_bytes() == b"\x89PNG\r\n\x1a\nrest"


@pytest.mark.asyncio
async def test_receive_upload_over_the_ceiling_leaves_nothing(tmp_path: Path) -> None:
    with pytest.raises(EditorAssetUploadTooLarge):
        await LocalArtifactRoot(tmp_path).receive_upload(
            asset_id="asset_1", chunks=chunks_of(b"a" * 40, b"b" * 40), max_bytes=64
        )

    assert leftovers(tmp_path) == []


@pytest.mark.asyncio
async def test_an_interrupted_upload_leaves_no_temporary_file(tmp_path: Path) -> None:
    with pytest.raises(ConnectionResetError):
        await LocalArtifactRoot(tmp_path).receive_upload(
            asset_id="asset_1", chunks=disconnecting(), max_bytes=64
        )

    assert leftovers(tmp_path) == []


@pytest.mark.parametrize("make_root", ["missing", "file"])
@pytest.mark.asyncio
async def test_receive_upload_refuses_a_missing_or_unusable_root(
    tmp_path: Path, make_root: str
) -> None:
    root = tmp_path / "artifacts"
    if make_root == "file":
        root.write_bytes(b"not a directory")

    with pytest.raises(ArtifactUnavailable):
        await LocalArtifactRoot(root).receive_upload(
            asset_id="asset_1", chunks=chunks_of(b"x"), max_bytes=64
        )

    assert not (tmp_path / "artifacts").is_dir()


@pytest.mark.asyncio
async def test_publish_upload_moves_atomically_to_a_project_scoped_locator(
    tmp_path: Path,
) -> None:
    root = LocalArtifactRoot(tmp_path)
    received = await root.receive_upload(
        asset_id="asset_1", chunks=chunks_of(b"media"), max_bytes=64
    )

    location = root.publish_upload(received, project_id="project_001", suffix=".png")

    assert location == "uploads/project_001/asset_1.png"
    assert (tmp_path / location).read_bytes() == b"media"
    assert leftovers(tmp_path) == [str(Path("uploads/project_001/asset_1.png"))]


@pytest.mark.parametrize("project_id", ["../escape", "a/b", "C:\\x", ".hidden", ""])
@pytest.mark.asyncio
async def test_publish_upload_refuses_an_unsafe_project_segment(
    tmp_path: Path, project_id: str
) -> None:
    root = LocalArtifactRoot(tmp_path)
    received = await root.receive_upload(
        asset_id="asset_1", chunks=chunks_of(b"media"), max_bytes=64
    )

    with pytest.raises(ArtifactPathInvalid):
        root.publish_upload(received, project_id=project_id, suffix=".png")


@pytest.mark.asyncio
async def test_discard_removes_a_temporary_or_published_upload(tmp_path: Path) -> None:
    root = LocalArtifactRoot(tmp_path)
    first = await root.receive_upload(asset_id="asset_1", chunks=chunks_of(b"a"), max_bytes=64)
    second = await root.receive_upload(asset_id="asset_2", chunks=chunks_of(b"b"), max_bytes=64)
    published = root.publish_upload(second, project_id="project_001", suffix=".png")

    root.discard(first.location)
    root.discard(published)
    root.discard(published)

    assert leftovers(tmp_path) == []


# --- render objects in the media store --------------------------------------
# `LocalArtifactRoot(tmp_path)` stores through `LocalMediaStore(tmp_path)`, so every object is
# a file under tmp_path that a test can assert on; the S3 store passes the same contract.


def test_prepare_makes_only_this_job_temporary_directory(tmp_path: Path) -> None:
    workspace = LocalArtifactRoot(tmp_path).prepare(JOB)

    assert (workspace.render_job_id, workspace.bundle_name, workspace.assets_name) == (
        JOB,
        "bundle.json",
        "assets",
    )
    assert str(tmp_path) not in repr(workspace)
    assert (tmp_path / "temp" / JOB).is_dir()
    assert not (tmp_path / "work" / JOB / "assets").exists()  # assets are no longer copied
    assert not (tmp_path / "temp" / OTHER_JOB).exists()


def test_stage_asset_verifies_a_stored_asset_without_copying_it(tmp_path: Path) -> None:
    root = LocalArtifactRoot(tmp_path)
    (tmp_path / "uploads" / "proj_1").mkdir(parents=True)
    (tmp_path / "uploads" / "proj_1" / "asset_1.mp4").write_bytes(b"clip")
    staged = root.stage_asset(
        root.prepare(JOB),
        asset_id="asset_1",
        location="uploads/proj_1/asset_1.mp4",
        expected_checksum=checksum_of(b"clip"),
        max_bytes=100,
    )

    assert (staged.asset_id, staged.relative_name, staged.size_bytes, staged.checksum) == (
        "asset_1",
        "assets/asset_1.mp4",
        4,
        checksum_of(b"clip"),
    )
    assert not (tmp_path / "work" / JOB / "assets").exists()


@pytest.mark.parametrize(
    ("checksum", "max_bytes", "location"),
    [
        (checksum_of(b"other"), 100, "uploads/proj_1/asset_1.mp4"),
        (checksum_of(b"clip"), 3, "uploads/proj_1/asset_1.mp4"),
        (checksum_of(b"clip"), 100, "uploads/proj_1/absent.mp4"),
        (checksum_of(b"clip"), 100, "../outside.mp4"),
    ],
)
def test_stage_asset_refuses_a_wrong_large_missing_or_unsafe_asset(
    tmp_path: Path, checksum: str, max_bytes: int, location: str
) -> None:
    root = LocalArtifactRoot(tmp_path)
    (tmp_path / "uploads" / "proj_1").mkdir(parents=True)
    (tmp_path / "uploads" / "proj_1" / "asset_1.mp4").write_bytes(b"clip")
    with pytest.raises(ArtifactUnavailable):
        root.stage_asset(
            root.prepare(JOB),
            asset_id="asset_1",
            location=location,
            expected_checksum=checksum,
            max_bytes=max_bytes,
        )


def test_read_bundle_returns_the_stored_bytes(tmp_path: Path) -> None:
    root = LocalArtifactRoot(tmp_path)
    assert root.write_bundle(root.prepare(JOB), b'{"bundle":1}') == "bundle.json"
    assert root.read_bundle(JOB) == b'{"bundle":1}'
    assert (tmp_path / "work" / JOB / "bundle.json").read_bytes() == b'{"bundle":1}'


def test_read_bundle_refuses_a_job_that_was_never_staged(tmp_path: Path) -> None:
    with pytest.raises(ArtifactUnavailable):
        LocalArtifactRoot(tmp_path).read_bundle(JOB)


@pytest.mark.asyncio
async def test_receive_output_stores_the_upload_under_work_and_reports_its_facts(
    tmp_path: Path,
) -> None:
    received = await LocalArtifactRoot(tmp_path).receive_output(
        JOB, chunks_of(b"ab", b"cd"), max_bytes=10
    )

    assert (received.size_bytes, received.checksum) == (4, checksum_of(b"abcd"))
    assert (tmp_path / "work" / JOB / "output.mp4").read_bytes() == b"abcd"
    assert not list((tmp_path / "temp").rglob("*.part"))


@pytest.mark.asyncio
async def test_receive_output_over_the_cap_stores_nothing(tmp_path: Path) -> None:
    with pytest.raises(RenderOutputTooLarge):
        await LocalArtifactRoot(tmp_path).receive_output(
            JOB, chunks_of(b"x" * 8, b"y" * 8), max_bytes=10
        )
    assert not (tmp_path / "work" / JOB / "output.mp4").exists()
    assert not list((tmp_path / "temp").rglob("*.part"))


@pytest.mark.asyncio
async def test_a_second_output_upload_replaces_the_first(tmp_path: Path) -> None:
    root = LocalArtifactRoot(tmp_path)
    await root.receive_output(JOB, chunks_of(b"old"), max_bytes=10)
    received = await root.receive_output(JOB, chunks_of(b"newer"), max_bytes=10)

    assert received.size_bytes == 5
    assert (tmp_path / "work" / JOB / "output.mp4").read_bytes() == b"newer"


@pytest.mark.asyncio
async def test_verify_temporary_output_names_the_matching_stored_output(tmp_path: Path) -> None:
    root = LocalArtifactRoot(tmp_path)
    await root.receive_output(JOB, chunks_of(b"render"), max_bytes=100)

    assert root.verify_temporary_output(JOB, facts(b"render")) == f"work/{JOB}/output.mp4"
    with pytest.raises(ArtifactUnavailable):
        root.verify_temporary_output(JOB, facts(b"render", size_bytes=99))
    with pytest.raises(ArtifactUnavailable):
        root.verify_temporary_output(JOB, facts(b"render", checksum=checksum_of(b"other")))


def test_a_missing_output_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(ArtifactUnavailable):
        LocalArtifactRoot(tmp_path).verify_temporary_output(JOB, facts(b"render"))


@pytest.mark.asyncio
async def test_publish_copies_the_verified_output_and_drops_the_work_objects(
    tmp_path: Path,
) -> None:
    root = LocalArtifactRoot(tmp_path)
    root.write_bundle(root.prepare(JOB), b"{}")
    await root.receive_output(JOB, chunks_of(b"render"), max_bytes=100)

    published = root.publish(JOB, facts(b"render"), b'{"m":1}', b'{"d":1}')

    assert (published.relative_path, published.size_bytes) == (f"renders/{JOB}/output.mp4", 6)
    assert (tmp_path / "renders" / JOB / "output.mp4").read_bytes() == b"render"
    assert (tmp_path / "renders" / JOB / "metadata.json").read_bytes() == b'{"m":1}'
    assert (tmp_path / "renders" / JOB / "diagnostics.json").read_bytes() == b'{"d":1}'
    assert not (tmp_path / "work" / JOB / "output.mp4").exists()
    assert not (tmp_path / "work" / JOB / "bundle.json").exists()


@pytest.mark.asyncio
async def test_publish_refuses_an_output_that_differs_from_its_facts(tmp_path: Path) -> None:
    root = LocalArtifactRoot(tmp_path)
    await root.receive_output(JOB, chunks_of(b"render"), max_bytes=100)

    with pytest.raises(ArtifactUnavailable):
        root.publish(JOB, facts(b"render", size_bytes=99), b"{}", b"{}")
    assert not (tmp_path / "renders" / JOB / "output.mp4").exists()


def test_resolve_download_only_names_this_job_published_render(tmp_path: Path) -> None:
    root = LocalArtifactRoot(tmp_path)
    assert root.resolve_download(JOB, f"renders/{JOB}/output.mp4") == f"renders/{JOB}/output.mp4"
    with pytest.raises(ArtifactPathInvalid):
        root.resolve_download(JOB, f"renders/{OTHER_JOB}/output.mp4")
    with pytest.raises(ArtifactPathInvalid):
        root.resolve_download(JOB, f"work/{JOB}/output.mp4")


def test_read_object_streams_a_range_of_a_published_render(tmp_path: Path) -> None:
    root = LocalArtifactRoot(tmp_path)
    (tmp_path / "renders" / JOB).mkdir(parents=True)
    (tmp_path / "renders" / JOB / "output.mp4").write_bytes(b"0123456789")

    assert root.object_size(f"renders/{JOB}/output.mp4") == 10
    assert b"".join(root.read_object(f"renders/{JOB}/output.mp4", 2, 4)) == b"234"
    with pytest.raises(ArtifactUnavailable):
        root.object_size(f"renders/{OTHER_JOB}/output.mp4")


@pytest.mark.asyncio
async def test_cleanup_deletes_the_output_and_work_objects_only(tmp_path: Path) -> None:
    root = LocalArtifactRoot(tmp_path)
    await root.receive_output(JOB, chunks_of(b"render"), max_bytes=100)
    root.publish(JOB, facts(b"render"), b"{}", b"{}")
    await root.receive_output(JOB, chunks_of(b"stray"), max_bytes=100)  # a late retry

    root.cleanup(JOB)
    root.cleanup(JOB)

    assert not (tmp_path / "renders" / JOB / "output.mp4").exists()
    assert (tmp_path / "renders" / JOB / "metadata.json").exists()
    assert (tmp_path / "renders" / JOB / "diagnostics.json").exists()
    work = tmp_path / "work" / JOB
    assert not work.exists() or not any(work.iterdir())


def test_cleanup_of_a_job_with_nothing_stored_is_a_no_op(tmp_path: Path) -> None:
    root = LocalArtifactRoot(tmp_path)
    root.cleanup(JOB)
    root.cleanup(JOB)
    assert not (tmp_path / "renders" / JOB).exists()


def test_a_linked_job_directory_is_never_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "elsewhere"
    outside.mkdir(parents=True)
    (tmp_path / "renders").mkdir()
    try:
        (tmp_path / "renders" / JOB).symlink_to(outside, target_is_directory=True)
    except OSError:  # pragma: no cover - unprivileged Windows session
        pytest.skip("this session cannot create a symlink")
    (outside / "output.mp4").write_bytes(b"planted")

    with pytest.raises(ArtifactPathInvalid):
        LocalArtifactRoot(tmp_path).cleanup(JOB)
    assert (outside / "output.mp4").exists()


@pytest.mark.asyncio
async def test_publish_upload_puts_the_file_in_the_store_and_drops_the_local_copy(
    tmp_path: Path,
) -> None:
    from thoth_control_plane.infrastructure.media_store import LocalMediaStore

    store_root = tmp_path / "store"
    store_root.mkdir()
    (tmp_path / "local").mkdir()
    root = LocalArtifactRoot(tmp_path / "local", LocalMediaStore(store_root))
    received = await root.receive_upload(
        asset_id="asset_1", chunks=chunks_of(b"clip"), max_bytes=10
    )

    location = root.publish_upload(received, project_id="proj_1", suffix=".mp4")

    assert location == "uploads/proj_1/asset_1.mp4"
    assert (store_root / location).read_bytes() == b"clip"
    assert not received.path.exists()
    assert not (tmp_path / "local" / location).exists()
    root.discard(location)
    assert not (store_root / location).exists()
