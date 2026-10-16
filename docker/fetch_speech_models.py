"""Fetch the pinned models: whisper, the two diarization ONNX files, and the footage embedding model.

Run by the Docker build (large-v3-turbo) and by CI (tiny, for tests). Every file is pinned by
revision or URL and verified by SHA-256; a mismatch exits non-zero (operator, 2026-10-13:
models are baked, never downloaded at run time).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

WHISPER = {
    "tiny": {
        "repo": "Systran/faster-whisper-tiny",
        "revision": "d90ca5fe260221311c53c58e660288d3deb8d356",
        "model_sha256": "dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1",
    },
    # faster-whisper maps large-v3-turbo to mobiuslabsgmbh/…, which now redirects here.
    "large-v3-turbo": {
        "repo": "dropbox-dash/faster-whisper-large-v3-turbo",
        "revision": "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
        "model_sha256": "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da",
    },
}
RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
DIARIZATION = {
    "segmentation.onnx": {
        "url": f"{RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
        "member": "sherpa-onnx-pyannote-segmentation-3-0/model.onnx",
        "sha256": "220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079",
    },
    "embedding.onnx": {
        "url": f"{RELEASES}/speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx",
        "member": None,
        "sha256": "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012",
    },
}
# Stage 5b story gate (spec 2026-10-14, amendment 2): the official ONNX export in fp32; the
# quantized exports score differently per CPU instruction set (2026-10-16).
EMBEDDING = {
    "repo": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "revision": "e8f8c211226b894fcb81acc59f3b34ba3efd5f42",
    "files": {
        "model.onnx": (
            "onnx/model.onnx",
            "10f7a088420252b26caf819236ca2c9d2987afd0fc06fec7553b542a5655a05a",
        ),
        "tokenizer.json": (
            "tokenizer.json",
            "2c3387be76557bd40970cec13153b3bbf80407865484b209e655e5e4729076b8",
        ),
    },
}


def verify(path: Path, expected: str) -> None:
    with path.open("rb") as handle:  # streamed: the turbo model is 1.6 GB
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != expected:
        sys.exit(f"checksum mismatch for {path.name}")


def fetch_whisper(size: str, out: Path) -> None:
    from huggingface_hub import snapshot_download

    pin = WHISPER[size]
    target = out / f"whisper-{size}"
    snapshot_download(pin["repo"], revision=pin["revision"], local_dir=target)
    verify(target / "model.bin", pin["model_sha256"])


def fetch_diarization(out: Path) -> None:
    target = out / "diarization"
    target.mkdir(parents=True, exist_ok=True)
    for name, asset in DIARIZATION.items():
        with tempfile.TemporaryDirectory() as scratch:
            download = Path(scratch) / "download"
            with urllib.request.urlopen(asset["url"], timeout=120) as response:  # noqa: S310
                download.write_bytes(response.read())
            if asset["member"] is not None:
                with tarfile.open(download) as archive:
                    member = archive.extractfile(asset["member"])
                    if member is None:
                        sys.exit(f"{asset['member']} missing from the archive")
                    (target / name).write_bytes(member.read())
            else:
                shutil.copyfile(download, target / name)
        verify(target / name, asset["sha256"])


def fetch_embedding(out: Path) -> None:
    from huggingface_hub import hf_hub_download

    target = out / "embedding"
    target.mkdir(parents=True, exist_ok=True)
    for name, (remote, digest) in EMBEDDING["files"].items():
        with tempfile.TemporaryDirectory() as scratch:
            path = hf_hub_download(
                EMBEDDING["repo"], remote, revision=EMBEDDING["revision"], local_dir=scratch
            )
            shutil.copyfile(path, target / name)
        verify(target / name, digest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--whisper", choices=sorted(WHISPER), required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    fetch_whisper(arguments.whisper, arguments.out)
    fetch_diarization(arguments.out)
    fetch_embedding(arguments.out)
