"""Periodic node registration through one WireGuard bootstrap."""

from __future__ import annotations

import json
import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request

from server.manager.domain.federation_transport import FederationTransport
from .config import _bootstrap_url

class FederationAnnouncer:
    """Register this node through one bootstrap Manager."""

    def __init__(
        self,
        *,
        bootstrap_url: str = "",
        register_url: str | None = None,
        registration_token: str,
        payload_factory: Callable[[], dict[str, object]],
        response_handler: Callable[[dict[str, object]], object] | None = None,
        transport: FederationTransport | None = None,
        interval: float = 10.0,
    ) -> None:
        legacy_url = str(register_url or "").strip()
        selected_url = str(bootstrap_url or "").strip()
        if legacy_url and selected_url and legacy_url != selected_url:
            raise ValueError("bootstrap_url conflicts with legacy register_url")
        self.bootstrap_url = _bootstrap_url(selected_url or legacy_url)
        self.registration_token = registration_token
        self.payload_factory = payload_factory
        self.response_handler = response_handler
        self.transport = transport or FederationTransport()
        self.interval = max(3.0, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_registration_urls: tuple[str, ...] = ()
        self._active_lock = threading.RLock()

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

    @property
    def active_registration_urls(self) -> tuple[str, ...]:
        with self._active_lock:
            return self._active_registration_urls

    def _post(
        self,
        url: str,
        payload: dict[str, object],
        *,
        expected_server_id: str = "",
    ) -> dict[str, object]:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
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
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("federation registration response must be an object")
        expected = str(expected_server_id or "").strip()
        if expected:
            responder = str(value.get("bootstrap_server_id") or "").strip()
            peer = value.get("peer")
            peer_id = (
                str(peer.get("server_id") or "").strip()
                if isinstance(peer, dict)
                else ""
            )
            if responder != expected or peer_id != expected:
                raise ValueError(
                    "direct registration responder does not match discovered node"
                )
        value["_roundtrip_ms"] = round(
            max(0.0, time.monotonic() - started) * 1000, 2,
        )
        if self.response_handler is not None:
            self.response_handler(value)
        return value

    def activate(self, server_id: str, registration_url: str) -> None:
        """Authenticate one discovered node only when a route needs it."""
        selected = _bootstrap_url(registration_url)
        if selected == self.bootstrap_url:
            return
        self._post(
            selected,
            self.payload_factory(),
            expected_server_id=server_id,
        )
        with self._active_lock:
            self._active_registration_urls = tuple(sorted({
                *self._active_registration_urls,
                selected,
            }))

    def run_once(self) -> None:
        """Renew the bootstrap and every directly discovered node once."""
        try:
            payload = self.payload_factory()
        except (OSError, ValueError, TypeError) as exc:
            # LAN snapshots expire during sleep/network changes. Skip this
            # renewal, never advertise stale addresses, and let the scheduler
            # retry after its normal interval rather than losing the thread.
            print(f"[federation] local registration unavailable: {exc}", flush=True)
            return
        try:
            self._post(self.bootstrap_url, payload)
        except (OSError, URLError, HTTPError, ValueError, TypeError) as exc:
            print(f"[federation] bootstrap unavailable: {exc}", flush=True)

        # Discovery alone never creates credentials.  Once an actual route has
        # activated a direct relationship, this same scheduler renews it.
        for url in self.active_registration_urls:
            try:
                self._post(url, payload)
            except (OSError, URLError, HTTPError, ValueError, TypeError) as exc:
                print(
                    f"[federation] direct registration unavailable ({url}): {exc}",
                    flush=True,
                )

    def _run(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self.interval)
