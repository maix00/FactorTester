"""Replicate canonical public factor sources to every registered Manager."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterable

from server.manager.services.factor_source_transfer import FactorSourceTransfer
from server.manager.storage.public_factor_replication import (
    PublicFactorReplicationStore,
)
from tools.data.factor_workspace.storage import load_public_factor_source


class PublicFactorReplicationService:
    def __init__(self, state: object, store: PublicFactorReplicationStore) -> None:
        self.state = state
        self.store = store
        self._lock = threading.RLock()

    def publish(
        self,
        factors: Iterable[dict[str, object]],
        *,
        principal: str,
    ) -> dict[str, object]:
        with self._lock:
            values = [self._verified_descriptor(item) for item in factors]
            self._declare(values, principal=principal)
            self.sync_pending()
            return self.store.summary(item["factor_id"] for item in values)

    def sync_pending(self) -> dict[str, int]:
        with self._lock:
            return self._sync_pending_locked()

    def _sync_pending_locked(self) -> dict[str, int]:
        peers = {
            str(item.get("server_id") or ""): item
            for item in self.state.federation_registry.servers(
                include_offline=True,
            )
        }
        for publication in self.store.publications():
            self._declare([publication], principal=str(publication["principal"]))
        report = {"completed": 0, "pending": 0, "failed": 0}
        for item in self.store.pending():
            target = str(item.get("target_server_id") or "")
            peer = peers.get(target)
            if not peer or not bool(peer.get("online", True)):
                self.store.record(
                    str(item["factor_id"]), target,
                    status="pending", error="registered target is offline",
                )
                report["pending"] += 1
                continue
            try:
                entry = self._source_entry(item)
                FactorSourceTransfer(self.state).stage(
                    [entry], principal=str(item.get("principal") or ""),
                    target_server_id=target,
                )
                self._invalidate_remote(
                    target, entry, principal=str(item.get("principal") or ""),
                )
                self.store.record(
                    str(item["factor_id"]), target, status="completed",
                )
                report["completed"] += 1
            except (ConnectionError, OSError, RuntimeError, TypeError, ValueError) as exc:
                self.store.record(
                    str(item["factor_id"]), target,
                    status="pending", error=str(exc),
                )
                report["failed"] += 1
        return report

    def _declare(
        self, values: Iterable[dict[str, object]], *, principal: str,
    ) -> None:
        targets = [str(self.state.server_id or "")]
        targets.extend(
            str(item.get("server_id") or "")
            for item in self.state.federation_registry.servers(
                include_offline=True,
            )
        )
        self.store.declare(
            values, targets, principal=principal,
            local_server_id=str(self.state.server_id or ""),
        )

    def _verified_descriptor(
        self, item: dict[str, object],
    ) -> dict[str, object]:
        factor_id = str(item.get("factor_id") or "").strip()
        source = load_public_factor_source(factor_id) or ""
        raw = source.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        if (
            not factor_id or not source.strip()
            or digest != str(item.get("source_sha256") or "").lower()
            or len(raw) != int(item.get("source_bytes") or -1)
        ):
            raise ValueError("public factor source changed before publication")
        return {
            "factor_id": factor_id,
            "source_sha256": digest,
            "source_bytes": len(raw),
        }

    def _source_entry(self, item: dict[str, object]) -> dict[str, object]:
        descriptor = self._verified_descriptor(item)
        factor_id = str(descriptor["factor_id"])
        return {
            **descriptor,
            "canonical_family_ref": f"public:{factor_id}",
            "source_kind": "public",
            "source_owner": "public",
            "source_access_policy": "public",
            "source_code": load_public_factor_source(factor_id) or "",
        }

    def _invalidate_remote(
        self, target: str, entry: dict[str, object], *, principal: str,
    ) -> None:
        route = self.state.route_for(server_id=target)
        response = self.state.route_request(
            route,
            path="/custom-factors/api/internal/public-source-applied",
            principal=principal,
            method="POST",
            body=json.dumps({
                "factors": [{
                    key: entry[key]
                    for key in ("factor_id", "source_sha256", "source_bytes")
                }],
            }).encode("utf-8"),
            content_type="application/json",
        )
        if not 200 <= int(response.status) < 300:
            raise ConnectionError("remote factor cache invalidation failed")


__all__ = ["PublicFactorReplicationService"]
