"""Threaded 7997 server composition for native transfer routes."""

from __future__ import annotations

from http.server import ThreadingHTTPServer

from server.manager.data_plane.context import DataPlaneRuntime
from server.manager.data_plane.handler import DataPlaneHandler


class DataPlaneHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        address,
        handler=DataPlaneHandler,
        *,
        runtime: DataPlaneRuntime,
    ) -> None:
        super().__init__(address, handler)
        self.runtime = runtime


__all__ = ["DataPlaneHTTPServer", "DataPlaneRuntime"]
