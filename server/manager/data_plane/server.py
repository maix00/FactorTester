"""Threaded client and peer data-plane server composition."""

from __future__ import annotations

from http.server import ThreadingHTTPServer

from server.manager.data_plane.context import DataPlaneRuntime
from server.manager.data_plane.handler import (
    ClientDataPlaneHandler,
    PeerDataPlaneHandler,
)


class DataPlaneHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler, *, runtime: DataPlaneRuntime) -> None:
        super().__init__(address, handler)
        self.runtime = runtime


class ClientDataPlaneHTTPServer(DataPlaneHTTPServer):
    def __init__(self, address, *, runtime: DataPlaneRuntime) -> None:
        super().__init__(address, ClientDataPlaneHandler, runtime=runtime)


class PeerDataPlaneHTTPServer(DataPlaneHTTPServer):
    def __init__(self, address, *, runtime: DataPlaneRuntime) -> None:
        super().__init__(address, PeerDataPlaneHandler, runtime=runtime)


__all__ = [
    "ClientDataPlaneHTTPServer",
    "DataPlaneHTTPServer",
    "DataPlaneRuntime",
    "PeerDataPlaneHTTPServer",
]
