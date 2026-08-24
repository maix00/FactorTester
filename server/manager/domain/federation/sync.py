"""Background synchronization of peer control-plane events."""

from __future__ import annotations

import threading
from typing import Any, Callable

from .gateway import FederatedGateway
from .models import ServiceRoute

class FederationSyncWorker:
    """Continuously pull relevant Manager events without opening a new port."""

    def __init__(
        self,
        *,
        server_id: str,
        job_index: Any,
        gateway: FederatedGateway,
        peer_provider: Callable[[], list[dict[str, object]]],
        local_refresh: Callable[[], None] | None = None,
        local_maintenance: Callable[[], None] | None = None,
        interval: float = 5.0,
    ) -> None:
        self.server_id = str(server_id or "").strip()
        self.job_index = job_index
        self.gateway = gateway
        self.peer_provider = peer_provider
        self.local_refresh = local_refresh
        self.local_maintenance = local_maintenance
        self.interval = max(2.0, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_report: list[dict[str, object]] = []

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="factor-manager-federation-control-sync",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2)
        self._thread = None

    def set_interval(self, interval: float) -> None:
        """Change the next polling interval without restarting the worker."""
        self.interval = max(2.0, min(300.0, float(interval)))

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "active": bool(self._thread and self._thread.is_alive()),
                "interval": self.interval,
                "last_report": [dict(item) for item in self._last_report],
            }

    @staticmethod
    def _route(peer: dict[str, object]) -> ServiceRoute:
        transfer_node = peer.get("transfer_node")
        transfer_node = transfer_node if isinstance(transfer_node, dict) else {}
        return ServiceRoute(
            server_id=str(peer.get("server_id") or ""),
            role=str(peer.get("role") or ""),
            branch=str(peer.get("branch") or ""),
            revision=str(peer.get("revision") or ""),
            port=7998,
            endpoint=str(peer.get("endpoint") or "").rstrip("/"),
            peer_control_endpoint=str(
                transfer_node.get("peer_control_endpoint") or ""
            ).rstrip("/"),
            peer_data_endpoint=str(
                transfer_node.get("peer_data_endpoint") or ""
            ).rstrip("/"),
            proxy_token=str(peer.get("proxy_token") or ""),
            remote=True,
            online=bool(peer.get("online", True)),
            public_server=bool(
                peer.get("public_server", peer.get("role") == "main")
            ),
        )

    def sync_once(self) -> list[dict[str, object]]:
        reports: list[dict[str, object]] = []
        if self.local_refresh is not None:
            try:
                self.local_refresh()
            except Exception as exc:
                reports.append({
                    "server_id": self.server_id,
                    "status": "local_refresh_error",
                    "error": str(exc),
                })
        if self.local_maintenance is not None:
            try:
                self.local_maintenance()
            except Exception as exc:
                reports.append({
                    "server_id": self.server_id,
                    "status": "local_maintenance_error",
                    "error": str(exc),
                })
        try:
            peers = list(self.peer_provider() or [])
        except Exception as exc:
            reports.append({"status": "error", "error": str(exc)})
            with self._lock:
                self._last_report = reports
            return reports
        for peer in peers:
            peer_id = str(peer.get("server_id") or "").strip()
            if not peer_id or peer_id == self.server_id:
                continue
            route = self._route(peer)
            if not route.online:
                reports.append({
                    "server_id": peer_id,
                    "status": "offline",
                })
                continue
            cursor = self.job_index.sync_cursor(peer_id)
            try:
                value = self.gateway.sync_events(
                    route,
                    requester_server_id=self.server_id,
                    after_sequence=cursor,
                )
                events = [
                    item for item in (value.get("events") or [])
                    if isinstance(item, dict)
                ]
                applied = self.job_index.apply_events(events)
                next_sequence = max(
                    cursor,
                    int(value.get("next_sequence") or cursor),
                )
                self.job_index.advance_sync_cursor(peer_id, next_sequence)
                reports.append({
                    "server_id": peer_id,
                    "status": "ok",
                    "received": len(events),
                    "applied": applied,
                    "next_sequence": next_sequence,
                    "has_more": bool(value.get("has_more")),
                })
            except (ConnectionError, OSError, TypeError, ValueError) as exc:
                reports.append({
                    "server_id": peer_id,
                    "status": "error",
                    "error": str(exc),
                })
        with self._lock:
            self._last_report = reports
        return reports

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sync_once()
            except Exception as exc:  # pragma: no cover - defensive daemon guard
                print(f"[federation] control sync failed: {exc}", flush=True)
            self._stop.wait(self.interval)
