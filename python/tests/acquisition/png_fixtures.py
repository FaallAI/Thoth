"""Deterministic PNG builders shared by the card tests."""

import random
import struct
import zlib


def make_png(width: int, height: int, *, flat: bool = False) -> bytes:
    """A valid RGB PNG: noisy pixels stay large like a real card, flat ones compress away."""
    rng = random.Random(width * 10_007 + height)
    row = width * 3
    raw = b"".join(b"\x00" + (bytes(row) if flat else rng.randbytes(row)) for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(kind + data))
        return struct.pack(">I", len(data)) + kind + data + crc

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
