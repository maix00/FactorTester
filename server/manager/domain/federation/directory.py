"""Credential-free, short-lived discovery metadata for federated nodes."""

from __future__ import annotations

import threading
import time


class FederationNodeDirectory:
    """Keep signed discoveries separate from authenticated service routes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, dict[str, object]] = {}

    def remember(
        self,
        node: dict[str, object],
        *,
        registration_url: str,
        expires_at: float,
    ) -> None:
        server_id = str(node.get("server_id") or "").strip()
        if not server_id:
            raise ValueError("federation directory server_id is required")
        if "proxy_token" in node:
            raise ValueError("federation directory must not contain credentials")
        with self._lock:
            self._records[server_id] = {
                "node": dict(node),
                "registration_url": str(registration_url),
                "expires_at": float(expires_at),
            }

    def nodes(self, *, now: float | None = None) -> list[dict[str, object]]:
        current = time.time() if now is None else float(now)
        with self._lock:
            self._purge_expired(current)
            values = [
                dict(record["node"])
                for record in self._records.values()
                if isinstance(record.get("node"), dict)
            ]
        return sorted(values, key=lambda item: str(item.get("server_id") or ""))

    def registration_url(
        self,
        server_id: str,
        *,
        now: float | None = None,
    ) -> str:
        current = time.time() if now is None else float(now)
        selected = str(server_id or "").strip()
        with self._lock:
            self._purge_expired(current)
            record = self._records.get(selected)
            if record is None:
                raise KeyError(selected)
            return str(record.get("registration_url") or "")

    def candidates(
        self,
        *,
        server_id: str = "",
        port: int | None = None,
        branch: str = "",
        feature: str = "",
        now: float | None = None,
    ) -> list[dict[str, object]]:
        return [
            node for node in self.nodes(now=now)
            if _node_matches(
                node,
                server_id=str(server_id or "").strip(),
                port=port,
                branch=str(branch or "").strip(),
                feature=str(feature or "").strip(),
            )
        ]

    def _purge_expired(self, now: float) -> None:
        expired = [
            server_id
            for server_id, record in self._records.items()
            if float(record.get("expires_at") or 0.0) <= now
        ]
        for server_id in expired:
            self._records.pop(server_id, None)


def _node_matches(
    node: dict[str, object],
    *,
    server_id: str,
    port: int | None,
    branch: str,
    feature: str,
) -> bool:
    if server_id and str(node.get("server_id") or "") != server_id:
        return False
    node_branch = str(node.get("branch") or "")
    node_features = {
        str(item) for item in (node.get("features") or [])
    }
    descriptors = [
        item
        for item in (node.get("ports") or [])
        if isinstance(item, dict) and bool(item.get("online", True))
    ]
    if port is not None:
        selected: list[dict[str, object]] = []
        for item in descriptors:
            try:
                descriptor_port = int(item.get("port") or 0)
            except (TypeError, ValueError):
                continue
            if descriptor_port == int(port):
                selected.append(item)
        descriptors = selected
    if branch:
        descriptors = [
            item for item in descriptors
            if str(item.get("branch") or node_branch) == branch
        ]
    if feature:
        descriptors = [
            item for item in descriptors
            if feature in {
                *node_features,
                *{
                    str(value)
                    for value in (item.get("features") or [])
                },
            }
        ]
    return bool(descriptors)
