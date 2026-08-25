"""On-demand hydration of factor sources required to freeze a RunSpec."""

from __future__ import annotations

import hashlib
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from server.manager.services.data_plane_client import loopback_client_access
from tools.data.sqlite.factor_source_store import upsert_factor_source


class FactorSourceHydrator:
    """Fetch one referenced source from its authoritative storage Manager."""

    def __init__(self, state: object) -> None:
        self.state = state

    def hydrate(self, factor_ref: str, *, principal: str) -> bool:
        owner, factor_id = self._identity(factor_ref, principal=principal)
        if not factor_id:
            return False
        for metadata in self._candidates(owner, factor_id, principal=principal):
            storage_server_id = str(metadata.get("storage_server_id") or "").strip()
            if not storage_server_id or storage_server_id == self.state.server_id:
                continue
            expected_size = int(metadata.get("source_bytes") or 0)
            expected_sha256 = str(metadata.get("source_sha256") or "").strip().lower()
            if expected_size <= 0 or len(expected_sha256) != 64:
                continue
            object_id = f"{owner}:{factor_id}"
            try:
                access = self.state.prepare_object_download(
                    principal=principal,
                    storage_server_id=storage_server_id,
                    object_kind="factor_source",
                    object_id=object_id,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    idempotency_key=(
                        f"hydrate-factor-source:{self.state.server_id}:"
                        f"{object_id}:{expected_sha256}"
                    ),
                    content_type="text/x-python",
                )
            except (ConnectionError, OSError, RuntimeError, TypeError, ValueError):
                continue
            download_url, tls_context = loopback_client_access(access.get("url"))
            request = Request(
                download_url,
                headers={"Authorization": f"Bearer {access.get('bearer') or ''}"},
                method="GET",
            )
            try:
                with urlopen(
                    request, timeout=120.0, context=tls_context,
                ) as response:
                    raw = response.read(expected_size + 1)
            except (HTTPError, URLError, OSError, TimeoutError, ConnectionError):
                continue
            if len(raw) != expected_size:
                continue
            if hashlib.sha256(raw).hexdigest() != expected_sha256:
                continue
            try:
                source = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            source_kind = "public" if owner == "public" else "custom"
            upsert_factor_source(
                source_kind,
                "" if source_kind == "public" else owner,
                factor_id,
                str(metadata.get("factor_name") or factor_id),
                source,
                chinese_name=str(metadata.get("chinese_name") or ""),
                description=str(metadata.get("description") or ""),
                category=str(metadata.get("category") or ""),
            )
            return True
        return False

    def _candidates(
        self, owner: str, factor_id: str, *, principal: str,
    ) -> list[dict[str, object]]:
        synchronizer = getattr(self.state, "account_domain_sync", None)
        if synchronizer is None:
            return []
        # Authorization is completed by the canonical factor-registry lookup
        # before hydration is attempted. Query the immutable source manifest
        # by its actual owner; using the submitting principal here hides a
        # direct subordinate's private provider rows from an otherwise
        # authorized delegated run.
        scope = "__public__" if owner == "public" else owner
        rows = synchronizer.entities(
            scope,
            entity_type="factor_source",
            include_shared=True,
            sync=True,
        )
        values = self._matching_payloads(
            rows, owner=owner, factor_id=factor_id,
        )
        # Repair mirrors created while the account-domain cursor skipped a
        # full page. This is metadata-only and bounded; source bytes still use
        # the 7997 data plane.
        control = getattr(synchronizer, "control_store", None)
        if control is None:
            return values
        after_revision = 0
        for _page in range(32):
            try:
                response = control.pull_account_domain_entities(
                    after_revision=after_revision, principal=scope, limit=1000,
                )
            except (AttributeError, ConnectionError, OSError, RuntimeError, TypeError, ValueError):
                return values
            remote_rows = response.get("entities") or []
            remote_values = self._matching_payloads(
                remote_rows, owner=owner, factor_id=factor_id,
            )
            if remote_values:
                for row in remote_rows:
                    if not isinstance(row, dict):
                        continue
                    payload = row.get("payload")
                    if isinstance(payload, dict) and payload in remote_values:
                        synchronizer.local.apply_remote(row)
                return [*values, *remote_values]
            next_revision = int(response.get("next_revision") or after_revision)
            if next_revision <= after_revision or len(remote_rows) < 1000:
                break
            after_revision = next_revision
        return values

    @staticmethod
    def _matching_payloads(
        rows: object, *, owner: str, factor_id: str,
    ) -> list[dict[str, object]]:
        values: list[dict[str, object]] = []
        for row in rows if isinstance(rows, list) else []:
            payload = row.get("payload") if isinstance(row, dict) else None
            if not isinstance(payload, dict):
                continue
            payload_owner = str(payload.get("owner_username") or "").strip()
            payload_kind = str(payload.get("source_kind") or "").strip()
            if str(payload.get("factor_id") or "").strip() != factor_id:
                continue
            if owner == "public" and payload_kind != "public":
                continue
            if owner != "public" and payload_owner != owner:
                continue
            values.append(payload)
        return values

    @staticmethod
    def _identity(factor_ref: str, *, principal: str) -> tuple[str, str]:
        value = str(factor_ref or "").strip()
        if ":" in value:
            owner, factor_id = value.split(":", 1)
            return owner.strip(), factor_id.strip()
        return str(principal or "").strip(), value


__all__ = ["FactorSourceHydrator"]
