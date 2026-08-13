"""Private-node agent: one outbound SSE, durable Inbox, then remote ACK."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from urllib.error import HTTPError, URLError

from server.manager.storage.transfers.inbox import TransferInboxStore
from server.manager.transfers.node_client import NodeControlClient
from server.manager.transfers.node_keys import NodeKey
from server.manager.transfers.models import NewTransferCommand, TransferCommandRecord


class NodeAgent:
    def __init__(
        self,
        *,
        inbox: TransferInboxStore,
        key: NodeKey,
        manager_endpoints: Callable[[], tuple[str, ...]],
        enrollment_token: str,
        data_endpoint: str,
        reachable_from: tuple[str, ...],
        retry_delay: float = 2.0,
    ) -> None:
        self.inbox = inbox
        self.key = key
        self.manager_endpoints = manager_endpoints
        self.enrollment_token = enrollment_token
        self.data_endpoint = str(data_endpoint or "").strip()
        self.reachable_from = tuple(sorted(set(reachable_from)))
        self.retry_delay = max(0.1, float(retry_delay))
        self.active_manager_endpoint = ""
        self._clients: dict[str, NodeControlClient] = {}
        self._enrolled: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _client(self, endpoint: str) -> NodeControlClient:
        selected = str(endpoint or "").strip().rstrip("/")
        if selected not in self._clients:
            self._clients[selected] = NodeControlClient(
                selected,
                key=self.key,
                enrollment_token=self.enrollment_token,
            )
        return self._clients[selected]

    def enroll(self, endpoint: str = "") -> dict[str, object]:
        selected = endpoint or next(iter(self.manager_endpoints()), "")
        if not selected:
            raise ConnectionError("no public Manager endpoint is configured")
        value = self._client(selected).enroll()
        self._enrolled.add(selected.rstrip("/"))
        self.active_manager_endpoint = selected.rstrip("/")
        return value

    def poll_once(
        self,
        *,
        timeout: float = 25.0,
        endpoint: str = "",
    ) -> list[TransferCommandRecord]:
        selected = (
            endpoint
            or self.active_manager_endpoint
            or next(iter(self.manager_endpoints()), "")
        ).rstrip("/")
        if not selected:
            raise ConnectionError("no public Manager endpoint is configured")
        client = self._client(selected)
        values = client.poll(
            after_sequence=self.inbox.latest_sequence(),
            data_endpoint=self.data_endpoint,
            reachable_from=self.reachable_from,
            timeout=timeout,
        )
        self.active_manager_endpoint = selected
        return self._persist_then_ack(client, values)

    def poll_healthy_once(
        self, *, timeout: float = 25.0,
    ) -> list[TransferCommandRecord]:
        failures: list[BaseException] = []
        for endpoint in self._ordered_endpoints():
            try:
                if endpoint not in self._enrolled:
                    self.enroll(endpoint)
                return self.poll_once(timeout=timeout, endpoint=endpoint)
            except (HTTPError, URLError, OSError, PermissionError, ConnectionError) as exc:
                failures.append(exc)
                self._enrolled.discard(endpoint)
        if failures:
            raise ConnectionError("no healthy public Manager is available") from failures[-1]
        raise ConnectionError("no public Manager endpoint is configured")

    def stream_once(
        self,
        *,
        endpoint: str = "",
        max_commands: int | None = None,
    ) -> list[TransferCommandRecord]:
        selected = (
            endpoint
            or self.active_manager_endpoint
            or next(iter(self.manager_endpoints()), "")
        ).rstrip("/")
        if not selected:
            raise ConnectionError("no public Manager endpoint is configured")
        client = self._client(selected)
        received: list[TransferCommandRecord] = []
        for value in client.stream(
            after_sequence=self.inbox.latest_sequence(),
            data_endpoint=self.data_endpoint,
            reachable_from=self.reachable_from,
        ):
            received.extend(self._persist_then_ack(client, [value]))
            self.active_manager_endpoint = selected
            if max_commands is not None and len(received) >= max_commands:
                break
        return received

    def _persist_then_ack(
        self,
        client: NodeControlClient,
        values: list[dict[str, object]],
    ) -> list[TransferCommandRecord]:
        result: list[TransferCommandRecord] = []
        for value in values:
            target = str(value.get("target_server_id") or "").strip()
            if target != self.key.node_id:
                raise PermissionError("node command targets another server")
            record = self.inbox.receive(NewTransferCommand(
                command_id=str(value.get("command_id") or ""),
                transfer_id=str(value.get("transfer_id") or ""),
                attempt_id=str(value.get("attempt_id") or ""),
                command_type=str(value.get("command_type") or ""),
                target_server_id=target,
                sequence=int(value.get("sequence") or 0),
                payload=(
                    value.get("payload")
                    if isinstance(value.get("payload"), dict) else {}
                ),
                expires_at=float(value.get("expires_at") or 0),
            ))
            client.acknowledge(record.command_id)
            result.append(record)
        return result

    def _ordered_endpoints(self) -> tuple[str, ...]:
        values = tuple(dict.fromkeys(
            str(value).strip().rstrip("/")
            for value in self.manager_endpoints()
            if str(value).strip()
        ))
        if self.active_manager_endpoint in values:
            return (self.active_manager_endpoint,) + tuple(
                value for value in values if value != self.active_manager_endpoint
            )
        return values

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="factor-manager-node-control",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        for client in tuple(self._clients.values()):
            client.close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_healthy_once(timeout=20.0)
                endpoint = self.active_manager_endpoint
                self.stream_once(endpoint=endpoint)
            except (HTTPError, URLError, OSError, PermissionError, ConnectionError):
                try:
                    self.poll_healthy_once(timeout=20.0)
                except (HTTPError, URLError, OSError, PermissionError, ConnectionError):
                    pass
            self._stop.wait(self.retry_delay)
