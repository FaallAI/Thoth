"""The media store contract (spec 2026-10-17); every store implementation passes the same tests."""

from __future__ import annotations

import os
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
S3_ENDPOINT = os.environ.get("THOTH_TEST_MEDIA_S3_ENDPOINT", "")
REQUIRED = os.environ.get("THOTH_REQUIRE_MINIO_TESTS") == "1"
if REQUIRED and not S3_ENDPOINT:
    raise RuntimeError("THOTH_REQUIRE_MINIO_TESTS=1 but THOTH_TEST_MEDIA_S3_ENDPOINT is unset")

STORES = [
    "local",
    pytest.param("s3", marks=pytest.mark.skipif(not S3_ENDPOINT, reason="needs a throwaway MinIO")),
]


def _s3_client():
    from minio import Minio

    return Minio(
        S3_ENDPOINT,
        access_key=os.environ["THOTH_TEST_MEDIA_S3_ACCESS_KEY"],
        secret_key=os.environ["THOTH_TEST_MEDIA_S3_SECRET_KEY"],
        secure=False,
    )


@pytest.fixture(params=STORES)
def store(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "local":
        root = tmp_path / "store"
        root.mkdir()
        yield LocalMediaStore(root)
        return
    import uuid

    from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore

    client = _s3_client()
    bucket = f"thoth-test-{uuid.uuid4().hex[:12]}"
    client.make_bucket(bucket)
    try:
        yield S3MediaStore(client, bucket)
    finally:
        for item in client.list_objects(bucket, recursive=True):
            client.remove_object(bucket, item.object_name)
        client.remove_bucket(bucket)


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
        "secrets/wf_a/x.mp4",
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


@pytest.mark.skipif(not S3_ENDPOINT, reason="needs a throwaway MinIO")
def test_the_s3_store_check_refuses_a_missing_bucket() -> None:
    from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore

    store = S3MediaStore(_s3_client(), "thoth-test-absent-bucket")
    with pytest.raises(MediaStoreUnavailable):
        store.check()
    store.ensure_bucket()
    try:
        store.check()
    finally:
        _s3_client().remove_bucket("thoth-test-absent-bucket")


def test_an_unreachable_s3_store_is_unavailable_not_missing(tmp_path: Path) -> None:
    import urllib3
    from minio import Minio

    from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore

    # Port 9 on loopback: nothing listens; no retries, so the request fails at once, offline.
    client = Minio(
        "127.0.0.1:9",
        access_key="a",
        secret_key="b",
        secure=False,
        http_client=urllib3.PoolManager(retries=urllib3.Retry(total=0)),
    )
    store = S3MediaStore(client, "thoth-media")
    with pytest.raises(MediaStoreUnavailable):
        store.stat(LOCATION)
    with pytest.raises(MediaStoreUnavailable):
        store.check()


def test_an_endpoint_without_both_keys_is_refused(tmp_path: Path) -> None:
    from thoth_control_plane.config import SettingsValidationError

    with pytest.raises(SettingsValidationError, match="media_s3_credentials_missing"):
        build_media_store(
            Settings(THOTH_CONTROL_PLANE_API_KEY="k", THOTH_MEDIA_S3_ENDPOINT="127.0.0.1:9")
        )


def test_an_endpoint_selects_the_s3_store(tmp_path: Path) -> None:
    from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore

    store = build_media_store(
        Settings(
            THOTH_CONTROL_PLANE_API_KEY="k",
            THOTH_MEDIA_S3_ENDPOINT="127.0.0.1:9",
            THOTH_MEDIA_S3_ACCESS_KEY="a",
            THOTH_MEDIA_S3_SECRET_KEY="b",
        )
    )
    assert isinstance(store, S3MediaStore)


@pytest.mark.skipif(not S3_ENDPOINT, reason="needs a throwaway MinIO")
def test_a_missing_bucket_on_an_object_request_is_an_outage(tmp_path: Path) -> None:
    from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore

    # minio reports a missing bucket on an object request as NoSuchKey; that is an outage.
    store = S3MediaStore(_s3_client(), "thoth-test-never-created")
    with pytest.raises(MediaStoreUnavailable):
        store.stat(LOCATION)
    with pytest.raises(MediaStoreUnavailable):
        store.fetch(LOCATION, tmp_path / "x.mp4")


def test_the_production_client_verifies_tls_with_the_certifi_bundle() -> None:
    import certifi

    from thoth_control_plane.infrastructure.s3_media_store import S3MediaStore

    store = S3MediaStore.from_settings(
        Settings(
            THOTH_CONTROL_PLANE_API_KEY="k",
            THOTH_MEDIA_S3_ENDPOINT="s3.example.test",
            THOTH_MEDIA_S3_ACCESS_KEY="a",
            THOTH_MEDIA_S3_SECRET_KEY="b",
            THOTH_MEDIA_S3_SECURE=True,
        )
    )
    pool = store._client._http.connection_pool_kw
    assert pool["cert_reqs"] == "CERT_REQUIRED"
    assert pool["ca_certs"] == certifi.where()


@pytest.mark.parametrize("prefix", ["uploads", "renders", "work", "archive"])
def test_the_new_prefixes_are_valid_locators(store, tmp_path: Path, prefix: str) -> None:
    location = f"{prefix}/job_1/output.mp4"
    store.put_file(location, _file(tmp_path, "o.mp4", b"out"))
    assert store.stat(location).size_bytes == 3


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [(0, None, b"0123456789"), (3, None, b"3456789"), (2, 5, b"2345"), (8, 99, b"89")],
)
def test_open_range_streams_the_requested_bytes(
    store, tmp_path: Path, start: int, end: int | None, expected: bytes
) -> None:
    store.put_file(LOCATION, _file(tmp_path, "d.mp4", b"0123456789"))
    assert b"".join(store.open_range(LOCATION, start, end)) == expected


def test_open_range_of_an_absent_object_is_unavailable(store) -> None:
    with pytest.raises(MediaUnavailable):
        b"".join(store.open_range(LOCATION))


def test_copy_keeps_the_bytes_and_the_digest(store, tmp_path: Path) -> None:
    source = _file(tmp_path, "s.mp4", b"render-bytes")
    store.put_file("work/rj_1/output.mp4", source)
    store.copy("work/rj_1/output.mp4", "renders/rj_1/output.mp4")
    copied = store.stat("renders/rj_1/output.mp4")
    assert copied.size_bytes == len(b"render-bytes")
    assert copied.sha256 == sha256_file(source)
    assert store.stat("work/rj_1/output.mp4").size_bytes == len(b"render-bytes")  # source stays


def test_copy_of_an_absent_object_is_unavailable(store) -> None:
    with pytest.raises(MediaUnavailable):
        store.copy("work/rj_1/output.mp4", "renders/rj_1/output.mp4")


def test_size_reports_the_object_size_without_reading_it(store, tmp_path: Path) -> None:
    store.put_file(LOCATION, _file(tmp_path, "s.mp4", b"0123456789"))
    assert store.size(LOCATION) == 10
    with pytest.raises(MediaUnavailable):
        store.size("reports/wf_a/media/absent.mp4")


def test_the_metered_store_records_scoped_writes_only(tmp_path) -> None:
    from tests.test_metering import Sink
    from thoth_control_plane import metering
    from thoth_control_plane.infrastructure.media_store import LocalMediaStore, MeteredMediaStore
    from thoth_control_plane.metering import MeterScope

    sink = Sink()
    metering.install(sink)
    store = MeteredMediaStore(LocalMediaStore(tmp_path / "root"))
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x" * 300)
    store.put_file("reports/wf_1/clip.mp4", source)  # no scope: the private renderer, a CLI
    with metering.scoped(MeterScope("ws_a", workflow_id="wf_1")):
        store.put_file("reports/wf_1/clip2.mp4", source)
    assert [(e.workspace_id, e.key, e.quantity) for e in sink.events] == [
        ("ws_a", "reports", 300.0)
    ]
    assert store.size("reports/wf_1/clip2.mp4") == 300
