"""Audio duration by PyAV (installed with the acquisition extra the image carries)."""

from __future__ import annotations

import io


def probe_duration(audio: bytes) -> float:
    import av

    with av.open(io.BytesIO(audio)) as container:
        if container.duration:
            return container.duration / av.time_base
        stream = container.streams.audio[0]
        return float(stream.duration * stream.time_base)
