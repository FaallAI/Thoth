"""Workflow media in an S3-compatible bucket (MinIO in Stage 1) through the `minio` SDK.

Every object records its sha256 as user metadata, so `stat` can compare without a download.
A `NoSuchKey` is `MediaUnavailable`; anything else that fails is `MediaStoreUnavailable`, whose
message is a fixed code: an SDK error can carry the endpoint and request details.
"""

from __future__ import annotations

import contextlib
import mimetypes
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import certifi
import urllib3
from minio import Minio
from minio.error import MinioException, S3Error

from thoth_control_plane.infrastructure.media_store import (
    MediaStat,
    MediaStoreUnavailable,
    MediaUnavailable,
    checked_locator,
    checked_prefix,
    sha256_file,
)

if TYPE_CHECKING:
    from thoth_control_plane.config import Settings

_MISSING = frozenset({"NoSuchKey", "NoSuchObject", "NotFound", "ResourceNotFound"})
_SHA_KEY = "x-amz-meta-sha256"


@contextlib.contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except S3Error as error:
        if error.code in _MISSING:
            raise MediaUnavailable("media_unavailable") from None
        raise MediaStoreUnavailable("media_store_unavailable") from None
    except (MinioException, urllib3.exceptions.HTTPError):
        raise MediaStoreUnavailable("media_store_unavailable") from None


class S3MediaStore:
    def __init__(self, client: Minio, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> S3MediaStore:
        from thoth_control_plane.config import SettingsValidationError

        access, secret = settings.THOTH_MEDIA_S3_ACCESS_KEY, settings.THOTH_MEDIA_S3_SECRET_KEY
        if not settings.THOTH_MEDIA_S3_ENDPOINT or access is None or secret is None:
            raise SettingsValidationError("media_s3_credentials_missing")
        # A custom pool replaces minio's own, so it carries minio's TLS defaults explicitly.
        http = urllib3.PoolManager(
            cert_reqs="CERT_REQUIRED",
            ca_certs=certifi.where(),
            timeout=urllib3.Timeout(connect=5.0, read=120.0),
            retries=urllib3.Retry(
                total=3, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504)
            ),
        )
        client = Minio(
            settings.THOTH_MEDIA_S3_ENDPOINT,
            access_key=access.get_secret_value(),
            secret_key=secret.get_secret_value(),
            secure=settings.THOTH_MEDIA_S3_SECURE,
            http_client=http,
        )
        return cls(client, settings.THOTH_MEDIA_S3_BUCKET)

    def put_file(self, location: str, path: Path) -> None:
        key = checked_locator(location)
        digest = sha256_file(path)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with _errors():
            self._client.fput_object(
                self._bucket,
                key,
                str(path),
                content_type=content_type,
                metadata={"sha256": digest},
            )

    def fetch(self, location: str, destination: Path) -> None:
        key = checked_locator(location)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # fget_object downloads to its own temporary name and renames it on success.
        with _errors():
            self._client.fget_object(self._bucket, key, str(destination))

    def stat(self, location: str) -> MediaStat:
        key = checked_locator(location)
        with _errors():
            found = self._client.stat_object(self._bucket, key)
        metadata = found.metadata or {}
        return MediaStat(size_bytes=int(found.size or 0), sha256=metadata.get(_SHA_KEY))

    def size(self, location: str) -> int:
        return self.stat(location).size_bytes

    def delete(self, location: str) -> None:
        key = checked_locator(location)
        with _errors():
            self._client.remove_object(self._bucket, key)

    def list(self, prefix: str) -> list[str]:
        checked_prefix(prefix)
        with _errors():
            return sorted(
                item.object_name
                for item in self._client.list_objects(self._bucket, prefix=prefix, recursive=True)
                if item.object_name and not item.is_dir
            )

    def open_range(self, location: str, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        key = checked_locator(location)
        length = None if end is None else max(0, end - start + 1)
        with _errors():
            response = self._client.get_object(self._bucket, key, offset=start, length=length or 0)
        return self._stream(response)

    @staticmethod
    def _stream(response) -> Iterator[bytes]:
        try:
            with _errors():
                yield from response.stream(1024 * 1024)
        finally:
            response.close()
            response.release_conn()

    def copy(self, source: str, destination: str) -> None:
        from minio.commonconfig import CopySource

        src, dst = checked_locator(source), checked_locator(destination)
        with _errors():
            self._client.copy_object(self._bucket, dst, CopySource(self._bucket, src))

    def check(self) -> None:
        with _errors():
            present = self._client.bucket_exists(self._bucket)
        if not present:
            raise MediaStoreUnavailable("media_bucket_missing")

    def ensure_bucket(self) -> None:
        """Create the private bucket when absent (the deploy's media import does this once)."""
        with _errors():
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
