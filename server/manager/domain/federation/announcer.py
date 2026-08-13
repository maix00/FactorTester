"""Periodic feature-Manager registration over WireGuard."""

from __future__ import annotations

import json
import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request

from server.manager.domain.federation_transport import FederationTransport
from .config import _peer_registration_url

class FederationAnnouncer:
    """Register a feature Manager to the remote control-plane Manager."""

    def __init__(
        self,
        *,
        register_url: str,
        registration_token: str,
        payload_factory: Callable[[], dict[str, object]],
        response_handler: Callable[[dict[str, object]], None] | None = None,
        transport: FederationTransport | None = None,
        interval: float = 10.0,
    ) -> None:
        self.register_url = _peer_registration_url(register_url)
        self.registration_token = registration_token
        self.payload_factory = payload_factory
        self.response_handler = response_handler
        self.transport = transport or FederationTransport()
        self.interval = max(3.0, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="factor-manager-federation-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2)
        self._thread = None

    def _post(self) -> None:
        payload = self.payload_factory()
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.register_url,
            data=raw,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.registration_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.monotonic()
        with self.transport.open(request, timeout=10) as response:
            raw = response.read(1024 * 1024)
        if self.response_handler is not None:
            value = json.loads(raw.decode("utf-8"))
            if isinstance(value, dict):
                value["_roundtrip_ms"] = round(
                    max(0.0, time.monotonic() - started) * 1000, 2,
                )
                self.response_handler(value)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._post()
            except (OSError, URLError, HTTPError, ValueError, TypeError) as exc:
                print(f"[federation] registration unavailable: {exc}", flush=True)
            self._stop.wait(self.interval)
