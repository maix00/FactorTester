"""Lazy synchronization service for account-domain metadata."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping

from server.manager.storage.account_domain.local import LocalAccountDomainStore
from server.manager.storage.account_domain.payloads import public_payload, validate_entity
from server.manager.storage.control_db import ControlDatabaseError


class AccountDomainSyncService:
    """Coordinate local SQLite, PostgreSQL, and bounded research metadata.

    SQLite is the local working copy and outbox. PostgreSQL is the shared
    authority when reachable. Reads invoke :meth:`sync` lazily; no background
    polling or extra network port is required.
    """

    def __init__(
        self,
        *,
        sqlite_path: str | Path,
        control_store: object | None,
        manager_id: str,
        access_cooldown: float = 5.0,
    ) -> None:
        self.local = LocalAccountDomainStore(sqlite_path)
        self.control_store = control_store
        self.manager_id = str(manager_id or "").strip()
        self.access_cooldown = max(0.0, float(access_cooldown))
        self._last_sync: dict[str, float] = {}
        self._last_reconcile: dict[str, float] = {}

    def upsert(
        self,
        principal: str,
        entity_type: str,
        entity_id: str,
        payload: Mapping[str, Any] | None,
        *,
        deleted: bool = False,
        flush: bool = True,
    ) -> dict[str, Any]:
        owner = str(principal or "").strip()
        if not owner:
            raise ValueError("account-domain principal is required")
        kind, identifier = validate_entity(entity_type, entity_id)
        clean = public_payload(payload)
        operation_id = self.local.upsert_local(
            principal=owner,
            entity_type=kind,
            entity_id=identifier,
            payload=clean,
            manager_id=self.manager_id,
            deleted=deleted,
        )
        result = {
            "status": "pending",
            "operation_id": operation_id,
            "principal": owner,
            "entity_type": kind,
            "entity_id": identifier,
        }
        if flush:
            result.update(self.flush(principal=owner))
        return result

    def delete(
        self, principal: str, entity_type: str, entity_id: str, *, flush: bool = True,
    ) -> dict[str, Any]:
        return self.upsert(
            principal, entity_type, entity_id, {}, deleted=True, flush=flush,
        )

    def sync(self, principal: str, *, force: bool = False, limit: int = 100) -> dict[str, Any]:
        owner = str(principal or "").strip()
        if not owner:
            return {"status": "skipped", "reason": "principal is empty"}
        now = time.monotonic()
        if not force and now - self._last_sync.get(owner, 0.0) < self.access_cooldown:
            return {"status": "cached", "principal": owner}
        self._last_sync[owner] = now
        flushed = self.flush(principal=owner, limit=limit)
        pulled = self.pull(principal=owner, limit=limit)
        return {"status": "synced", "principal": owner, "flushed": flushed, "pulled": pulled}

    def flush(self, *, principal: str = "", limit: int = 100) -> dict[str, Any]:
        pending = self.local.pending(principal=principal, limit=limit)
        if not pending:
            return {"sent": 0, "pending": 0, "conflicts": 0}
        if self.control_store is None:
            return {"sent": 0, "pending": len(pending), "conflicts": 0, "offline": True}
        sent = conflicts = 0
        for item in pending:
            try:
                receipt = self.control_store.push_account_domain_entity(
                    principal=item["principal"],
                    entity_type=item["entity_type"],
                    entity_id=item["entity_id"],
                    payload=item["payload"],
                    deleted=item["deleted"],
                    base_revision=item["base_revision"],
                    origin_manager_id=self.manager_id,
                    operation_id=item["operation_id"],
                )
                if str(receipt.get("status") or "") == "conflict":
                    conflicts += 1
                    self.local.record_push_conflict(item, receipt)
                    self.local.mark_attempt(item["operation_id"], "remote revision conflict")
                    continue
                self.local.acknowledge(
                    item["operation_id"], revision=int(receipt.get("revision") or 0),
                )
                sent += 1
            except (AttributeError, ControlDatabaseError, ConnectionError, OSError, RuntimeError, TypeError, ValueError) as exc:
                self.local.mark_attempt(item["operation_id"], str(exc))
                return {
                    "sent": sent,
                    "pending": len(pending) - sent,
                    "conflicts": conflicts,
                    "offline": True,
                }
        return {"sent": sent, "pending": len(pending) - sent, "conflicts": conflicts}

    def pull(self, *, principal: str, limit: int = 100) -> dict[str, Any]:
        if self.control_store is None:
            return {"applied": 0, "conflicts": 0, "offline": True}
        scope = self._cursor_scope(principal)
        after = self.local.cursor(scope)
        try:
            response = self.control_store.pull_account_domain_entities(
                after_revision=after,
                principal=principal,
                limit=limit,
            )
        except (AttributeError, ControlDatabaseError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
            return {"applied": 0, "conflicts": 0, "offline": True}
        applied = conflicts = 0
        maximum = after
        for row in response.get("entities") or []:
            if not isinstance(row, dict):
                continue
            maximum = max(maximum, int(row.get("revision") or 0))
            state = self.local.apply_remote(row)
            if state == "applied":
                applied += 1
            elif state == "conflict":
                conflicts += 1
        self.local.advance_cursor(scope, max(maximum, int(response.get("next_revision") or maximum)))
        return {"applied": applied, "conflicts": conflicts, "next_revision": maximum}

    def entities(
        self,
        principal: str,
        *,
        entity_type: str = "",
        include_shared: bool = True,
        sync: bool = True,
    ) -> list[dict[str, Any]]:
        if sync:
            self.sync(principal)
        return self.local.list_entities(
            principal=principal,
            entity_type=entity_type,
            include_shared=include_shared,
        )

    def sync_research_publication(
        self,
        publication: Mapping[str, Any],
        *,
        deleted: bool = False,
        flush: bool = True,
    ) -> dict[str, Any]:
        owner = str(publication.get("owner_ref") or "").strip()
        publication_id = str(publication.get("publication_id") or "").strip()
        if not owner or not publication_id:
            raise ValueError("research publication metadata is incomplete")
        return self.upsert(
            owner,
            "research_publication",
            publication_id,
            publication,
            deleted=deleted,
            flush=flush,
        )

    def reconcile_research_library(self, library: object) -> int:
        """Seed metadata for publications created before the generic outbox."""
        try:
            values = library.list_metadata()
        except (AttributeError, OSError, TypeError, ValueError):
            return 0
        count = 0
        current_ids: set[tuple[str, str]] = set()
        for publication in values:
            if not isinstance(publication, Mapping):
                continue
            try:
                self.sync_research_publication(
                    publication, deleted=False, flush=False,
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                continue
            count += 1
            current_ids.add((
                str(publication.get("owner_ref") or ""),
                str(publication.get("publication_id") or ""),
            ))
        # Only tombstone rows whose bytes are owned by this Manager. A pulled
        # public row belongs to another storage node and must not be revoked
        # merely because its local mirror is absent.
        for row in self.local.list_entities(
            entity_type="research_publication", include_shared=False,
        ):
            payload = row.get("payload") if isinstance(row, dict) else None
            if not isinstance(payload, dict):
                continue
            owner = str(row.get("principal") or "")
            publication_id = str(row.get("entity_id") or "")
            storage_id = str(
                payload.get("storage_server_id") or row.get("origin_manager_id") or ""
            )
            if (
                storage_id == self.manager_id
                and (owner, publication_id) not in current_ids
            ):
                self.delete(
                    owner, "research_publication", publication_id, flush=False,
                )
                count += 1
        if count:
            self.flush()
        return count

    def reconcile_principal(self, principal: str) -> int:
        """Backfill existing local factor/catalog rows into the outbox."""
        owner = str(principal or "").strip()
        if not owner:
            return 0
        now = time.monotonic()
        if now - self._last_reconcile.get(owner, 0.0) < self.access_cooldown:
            return 0
        self._last_reconcile[owner] = now
        count = 0
        try:
            from tools.data.account_manage import (
                list_factor_research_runs,
                list_factor_sets,
                list_factor_param_config_aliases,
                list_factor_param_config_scopes,
                load_factor_param_config,
                load_product_categories,
                load_product_groups,
            )
            categories = load_product_categories(owner)
            groups = load_product_groups(owner)
            sets = list_factor_sets(owner)
            for value in categories:
                if self._reconcile_value(owner, "product_category", value, "id"):
                    count += 1
            for value in groups:
                if self._reconcile_value(owner, "product_group", value, "id"):
                    count += 1
            for value in sets:
                identifier = str(
                    value.get("target_ref") or value.get("set_ref") or ""
                )
                if identifier:
                    self.upsert(owner, "factor_set", identifier, value, flush=False)
                    count += 1
            for scope in list_factor_param_config_scopes(owner):
                for alias in list_factor_param_config_aliases(owner, scope):
                    value = load_factor_param_config(owner, alias, scope)
                    if isinstance(value, dict):
                        self.upsert(
                            owner, "factor_param_config", f"{scope}:{alias}",
                            value, flush=False,
                        )
                        count += 1
            for value in list_factor_research_runs(owner, limit=512):
                identifier = str(value.get("run_id") or "")
                if identifier:
                    self.upsert(
                        owner, "factor_research_run", identifier, value, flush=False,
                    )
                    count += 1
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            pass
        count += self.reconcile_factor_sources(owner)
        if count:
            self.flush(principal=owner)
        return count

    def reconcile_factor_sources(self, principal: str = "") -> int:
        """Backfill source manifests; source bodies never enter the payload."""
        try:
            from tools.data.sqlite.factor_source_store import list_factor_sources
        except ImportError:
            return 0
        count = 0
        for source_kind in ("custom", "public"):
            for value in list_factor_sources(source_kind):
                owner = str(value.get("owner_username") or "").strip()
                target = owner or "__public__"
                if source_kind == "custom" and target != str(principal or "").strip():
                    continue
                factor_id = str(value.get("factor_id") or "").strip()
                if not factor_id:
                    continue
                source_code = str(value.get("source_code") or "")
                import hashlib

                payload = {
                    "source_kind": source_kind,
                    "owner_username": owner,
                    "factor_id": factor_id,
                    "factor_name": str(value.get("factor_name") or factor_id),
                    "source_sha256": hashlib.sha256(source_code.encode()).hexdigest(),
                    "source_bytes": len(source_code.encode()),
                    "storage_server_id": self.manager_id,
                    "visibility": "public" if source_kind == "public" else "private",
                }
                self.upsert(
                    target, "factor_source", f"{source_kind}:{factor_id}",
                    payload, flush=False,
                )
                count += 1
        if count:
            self.flush()
        return count

    def _reconcile_value(
        self, principal: str, entity_type: str, value: Any, id_key: str,
    ) -> bool:
        if not isinstance(value, Mapping):
            return False
        identifier = str(value.get(id_key) or "").strip()
        if not identifier:
            return False
        self.upsert(principal, entity_type, identifier, value, flush=False)
        return True

    @staticmethod
    def _cursor_scope(principal: str) -> str:
        return f"account-domain:{str(principal or '').strip()}"
