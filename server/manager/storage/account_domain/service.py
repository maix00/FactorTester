"""Lazy synchronization service for account-domain metadata."""

from __future__ import annotations

import time
import hashlib
from pathlib import Path
from typing import Any, Mapping

from server.manager.storage.account_domain.local import LocalAccountDomainStore
from server.manager.storage.account_domain.payloads import (
    public_payload,
    validate_entity,
)
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
        # Existing local rows may predate the generic account-domain outbox.
        # Reconcile them at the same lazy boundary used by Web, Swift, and CLI
        # reads so source-provider manifests are available before peers need
        # to hydrate immutable factor source bytes over the data plane.
        reconciled = self.reconcile_principal(owner)
        flushed = self.flush(principal=owner, limit=limit)
        pulled = self.pull(principal=owner, limit=limit)
        # After pulling factor_source manifests, localize version history for any
        # source whose bytes are already present locally.  A receiver that never
        # authored the source still records its formula versions, so
        # factor_family_formula_versions converges across servers (body is pulled
        # lazily over the data plane; the fingerprint arrives via outbox).
        versioned = self.materialize_factor_source_versions(owner)
        return {
            "status": "incomplete" if (flushed.get("pending") or flushed.get("offline") or pulled.get("offline")) else "synced",
            "principal": owner,
            "reconciled": reconciled,
            "flushed": flushed,
            "pulled": pulled,
            "versioned": versioned,
        }

    def materialize_factor_source_versions(self, principal: str = "") -> int:
        """Record local formula-version history for factor sources we already hold.

        Reconcile/pull carries the ``family_formula_fingerprint`` on each
        ``factor_source`` manifest, but the ``factor_family_formula_versions``
        table is only written on the authoring server.  This pass backfills a
        version row for every factor source whose bytes are present locally,
        using the fingerprint advertised by the origin — so the version history
        (and the source-version picker) is no longer empty on a receiver.
        """
        count = 0
        try:
            from tools.data.sqlite.factor_source_store import load_factor_source
            from tools.data.sqlite.factor_source_versions import (
                record_factor_formula_version, load_factor_formula_version,
            )
        except ImportError:
            return 0
        target = str(principal or "").strip()
        for row in self.local.list_entities(
            principal=target, entity_type="factor_source",
        ):
            payload = (row.get("payload") or {}) if isinstance(row, dict) else {}
            if not isinstance(payload, dict):
                continue
            source_kind = str(payload.get("source_kind") or "").strip()
            factor_id = str(payload.get("factor_id") or "").strip()
            fingerprint = str(
                payload.get("family_formula_fingerprint") or ""
            ).strip()
            owner_username = str(payload.get("owner_username") or "").strip()
            if not source_kind or not factor_id or not fingerprint:
                continue
            if load_factor_formula_version(source_kind, owner_username, factor_id, fingerprint):
                continue
            # Only localize when we already hold the body (bytes).  Bodies travel
            # over the data plane via the hash-bound transfer; manifests carry the
            # fingerprint.  If the body is absent, skip (hydrated on demand).
            body = load_factor_source(source_kind, owner_username, factor_id)
            if not body or hashlib.sha256(body.encode("utf-8")).hexdigest() != payload.get("source_sha256"):
                continue
            try:
                record_factor_formula_version(
                    source_kind,
                    owner_username,
                    factor_id,
                    body,
                    family_formula_fingerprint=fingerprint,
                    subject=f"reconcile: {source_kind} {factor_id}",
                )
                count += 1
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                continue
        return count

    def flush(self, *, principal: str = "", limit: int = 100) -> dict[str, Any]:
        pending = self.local.pending(principal=principal, limit=limit)
        if not pending:
            return {"sent": 0, "conflicts": 0, **self.local.sync_state(principal=principal)}
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
                    item["operation_id"], revision=int(receipt.get("revision") or 0), sent_item=item,
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
        return {"sent": sent, "conflicts": conflicts, **self.local.sync_state(principal=principal)}

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
        include_deleted: bool = False,
        sync: bool = True,
    ) -> list[dict[str, Any]]:
        if sync:
            self.sync(principal)
        return self.local.list_entities(
            principal=principal,
            entity_type=entity_type,
            include_shared=include_shared,
            include_deleted=include_deleted,
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
                load_product_categories,
                load_product_groups,
            )
            categories = load_product_categories(owner)
            groups = load_product_groups(owner)
            for value in categories:
                if self._reconcile_value(owner, "product_category", value, "id"):
                    count += 1
            for value in groups:
                if self._reconcile_value(owner, "product_group", value, "id"):
                    count += 1
            count += self.reconcile_factor_catalog(
                owner, force=True, flush=False,
            )
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

    def reconcile_factor_catalog(
        self,
        principal: str,
        *,
        force: bool = False,
        flush: bool = True,
    ) -> int:
        """Materialize local factor aliases without scanning unrelated domains."""
        owner = str(principal or "").strip()
        if not owner:
            return 0
        cooldown_key = f"factor-catalog:{owner}"
        now = time.monotonic()
        if (
            not force
            and now - self._last_reconcile.get(cooldown_key, 0.0)
            < self.access_cooldown
        ):
            return 0
        self._last_reconcile[cooldown_key] = now
        try:
            from tools.data.account_manage import list_factor_sets

            from .factor_sync import materialized_factor_configs

            values = {
                "factor_set": [
                    (
                        str(item.get("ref") or item.get("target_ref") or item.get("set_ref") or ""),
                        item,
                    )
                    for item in list_factor_sets(owner)
                    if isinstance(item, Mapping)
                ],
                "factor_param_config": materialized_factor_configs(owner, existing=self.local.list_entities(
                    principal=owner, entity_type="factor_param_config", include_shared=False,
                )),
            }
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return 0

        count = 0
        for entity_type, items in values.items():
            existing = {
                str(row.get("entity_id") or ""): row
                for row in self.local.list_entities(
                    principal=owner,
                    entity_type=entity_type,
                    include_shared=False,
                )
            }
            current_ids: set[str] = set()
            for identifier, value in items:
                identifier = str(identifier or "").strip()
                if not identifier or not isinstance(value, Mapping):
                    continue
                current_ids.add(identifier)
                row = existing.get(identifier)
                if entity_type == "factor_set" and row is not None:
                    # Save/delete hooks already persist immutable set changes.
                    # A retained authoring copy must not replace a peer mirror.
                    continue
                clean = public_payload(value)
                if (
                    row is not None
                    and row.get("payload") == clean
                ):
                    continue
                self.upsert(
                    owner, entity_type, identifier, clean, flush=False,
                )
                count += 1
            # Absence from an authored collection is not proof of deletion:
            # this Manager may only hold peer projections or lack a dependency.
            # Explicit authoring delete APIs already enqueue tombstones.
        if count and flush:
            self.flush(principal=owner)
        return count

    def reconcile_factor_sources(self, principal: str = "") -> int:
        """Backfill one source manifest per storage provider, without bodies."""
        try:
            from tools.data.sqlite.factor_metadata import list_factor_summaries
        except ImportError:
            return 0
        count = 0
        existing_by_principal: dict[str, dict[str, dict[str, Any]]] = {}
        pending_by_principal: dict[str, dict[str, dict[str, Any]]] = {}
        for source_kind in ("custom", "public"):
            for value in list_factor_summaries(source_kind, str(principal or "").strip() if source_kind == "custom" else ""):
                owner = str(value.get("owner_username") or "").strip()
                target = owner or "__public__"
                if source_kind == "custom" and target != str(principal or "").strip():
                    continue
                factor_id = str(value.get("factor_id") or "").strip()
                if not factor_id:
                    continue
                payload = {
                    "source_kind": source_kind,
                    "owner_username": owner,
                    "factor_id": factor_id,
                    "factor_name": str(value.get("name") or value.get("factor_name") or factor_id),
                    "catalog": value,
                    "source_sha256": str(value.get("source_sha256") or ""),
                    "source_bytes": int(value.get("source_bytes") or 0),
                    "storage_server_id": self.manager_id,
                    "visibility": "public" if source_kind == "public" else "private",
                    # Carry the immutable semantic fingerprint so a receiving
                    # server converges its factor_family_formula_versions local
                    # mirror even though the source body is pulled lazily.
                    "family_formula_fingerprint": str(
                        value.get("family_formula_fingerprint") or ""
                    ).strip(),
                }
                # Source identity and storage availability are different
                # dimensions. The same immutable source may be present on
                # several Managers, so each provider owns an independent row.
                entity_id = f"{source_kind}:{factor_id}@{self.manager_id}"
                if target not in existing_by_principal:
                    existing_by_principal[target] = {
                        str(row.get("entity_id") or ""): row
                        for row in self.local.list_entities(
                            principal=target,
                            entity_type="factor_source",
                            include_shared=False,
                        )
                    }
                existing = existing_by_principal[target]
                current = existing.get(entity_id)
                clean = public_payload(payload)
                if not (
                    current is not None
                    and current.get("payload") == clean
                    and str(current.get("origin_manager_id") or "")
                    == self.manager_id
                ):
                    self.upsert(
                        target, "factor_source", entity_id,
                        clean, flush=False,
                    )
                    count += 1

                # Versions before provider-scoped identities wrote every
                # server to the same row. Retire only this Manager's matching
                # pending override; never delete another provider's authority.
                legacy_id = f"{source_kind}:{factor_id}"
                if target not in pending_by_principal:
                    pending_by_principal[target] = {
                        str(item.get("entity_id") or ""): item
                        for item in self.local.pending(
                            principal=target, limit=1000, include_blocked=True,
                        )
                        if item.get("entity_type") == "factor_source"
                    }
                pending = pending_by_principal[target].get(legacy_id)
                pending_payload = (pending or {}).get("payload") or {}
                if (
                    pending is not None
                    and pending_payload.get("source_sha256")
                    == payload["source_sha256"]
                ):
                    self.local.discard_local_entity(
                        target, "factor_source", legacy_id,
                    )
                    pending_by_principal[target].pop(legacy_id, None)
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
