"""In-process wake-up hub backed by durable node commands and presence."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable

from server.manager.storage.transfers.node_commands import NodeCommandQueue
from server.manager.storage.transfers.node_presence import NodePresenceStore
from server.manager.transfers.node_models import (
    NewNodeCommand,
    NodeCommandRecord,
    NodeConnection,
)


class NodeControlHub:
    def __init__(
        self,
        commands: NodeCommandQueue,
        presence: NodePresenceStore,
        *,
        manager_id: str,
        presence_ttl: float = 30.0,
    ) -> None:
        self.commands = commands
        self.presence = presence
        self.manager_id = str(manager_id or "").strip()
        self.presence_ttl = presence_ttl
        self._condition = threading.Condition()
        self._connections: dict[str, str] = {}

    def attach(
        self,
        *,
        node_id: str,
        data_endpoint: str,
        reachable_from: tuple[str, ...] | frozenset[str],
        now: float | None = None,
    ) -> NodeConnection:
        connection = NodeConnection(
            node_id=str(node_id), connection_id=secrets.token_hex(16),
        )
        current = time.time() if now is None else float(now)
        with self._condition:
            self._connections[connection.node_id] = connection.connection_id
            self._condition.notify_all()
        self.presence.observe(
            node_id=connection.node_id,
            connection_owner_manager_id=self.manager_id,
            connection_id=connection.connection_id,
            data_endpoint=data_endpoint,
            reachable_from=reachable_from,
            ttl=self.presence_ttl,
            now=current,
        )
        return connection

    def is_current(self, connection: NodeConnection) -> bool:
        with self._condition:
            return self._connections.get(
                connection.node_id
            ) == connection.connection_id

    def detach(
        self, connection: NodeConnection, *, now: float | None = None,
    ) -> None:
        if self.is_current(connection):
            with self._condition:
                self._connections.pop(connection.node_id, None)
            self.presence.mark_offline(
                node_id=connection.node_id,
                connection_id=connection.connection_id,
                now=now,
            )

    def refresh(
        self,
        connection: NodeConnection,
        *,
        data_endpoint: str,
        reachable_from: tuple[str, ...] | frozenset[str],
        now: float | None = None,
    ) -> bool:
        if not self.is_current(connection):
            return False
        self.presence.observe(
            node_id=connection.node_id,
            connection_owner_manager_id=self.manager_id,
            connection_id=connection.connection_id,
            data_endpoint=data_endpoint,
            reachable_from=reachable_from,
            ttl=self.presence_ttl,
            now=now,
        )
        return True

    def observe_poll(
        self,
        *,
        node_id: str,
        data_endpoint: str,
        reachable_from: tuple[str, ...] | frozenset[str],
        now: float | None = None,
    ) -> None:
        self.presence.observe(
            node_id=node_id,
            connection_owner_manager_id=self.manager_id,
            connection_id=f"poll-{node_id}",
            data_endpoint=data_endpoint,
            reachable_from=reachable_from,
            ttl=self.presence_ttl,
            now=now,
        )

    def enqueue(
        self, command: NewNodeCommand, *, now: float | None = None,
    ) -> NodeCommandRecord:
        record = self.commands.enqueue(command, now=now)
        with self._condition:
            self._condition.notify_all()
        return record

    def poll(
        self,
        *,
        node_id: str,
        after_sequence: int,
        timeout: float = 25.0,
        include_replay: bool = True,
        now: Callable[[], float] = time.time,
    ) -> list[NodeCommandRecord]:
        deadline = time.monotonic() + max(0.0, min(30.0, float(timeout)))
        while True:
            pending = self.commands.pending(
                node_id=node_id,
                after_sequence=after_sequence,
                include_replay=include_replay,
                now=now(),
            )
            if pending:
                return pending
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return []
            with self._condition:
                self._condition.wait(timeout=remaining)
