import socket

import pytest


def test_non_loopback_connections_are_refused_in_offline_tests() -> None:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        with pytest.raises(ConnectionRefusedError, match="blocked in offline tests"):
            sock.connect(("203.0.113.1", 443))  # TEST-NET-3, never routable


def test_loopback_connections_stay_allowed() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        with socket.socket() as sock:
            sock.connect(server.getsockname())
