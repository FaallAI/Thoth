#!/usr/bin/env bash
# Prove the image's stealthy browser stack can actually launch. `scrapling install` installs
# playwright's Chromium while the stealthy sessions launch through patchright, which pins its
# own revision: the 2026-10-23 dependency refresh shipped patchright 1.64.2 with only
# playwright 1.62.0's chromium-1234, so every card visit failed before any request — and was
# classified headless_blocked, the same string a login wall logs. Builds nothing: the image
# to test is the only argument. Offline: the probe starts the driver and checks the binary.
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "usage: docker/test-browser-offline.sh IMAGE" >&2
    exit 64
fi

docker run --rm --network none \
    --entrypoint /opt/thoth/python/.venv/bin/python "$1" -c "
import asyncio

from thoth_control_plane.acquisition.browser import check_scrapling_capability

capability = asyncio.run(check_scrapling_capability())
assert capability.available, f'scrapling capability unavailable: {capability.code}'
print('scrapling_capability=true')
"
