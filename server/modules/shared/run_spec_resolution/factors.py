"""Reconstruct runtime Factor objects from immutable RunSpecs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from server.modules.shared.factor_param_utils import unique_frozen_factor_records
from tools.factors.formula_identity import require_frozen_factor


class RunFactorResolver:
    """Resolve roots against one complete frozen factor graph.

    Test modules choose the root ref they execute.  This class alone owns the
    transport-to-runtime reconstruction, including external artifacts and
    recursive FactorParam dependencies.
    """

    def __init__(
        self,
        *,
        owner: str,
        frozen_factors: Any = None,
        external_factor_artifacts: Any = None,
        page_factors: Mapping[str, Any] | None = None,
        page_uuid: str = "",
    ) -> None:
        self.owner = str(owner or "").strip()
        self.records = unique_frozen_factor_records(frozen_factors or [])
        self.frozen_by_ref = {record["ref"]: record for record in self.records}
        self.external_factor_artifacts = external_factor_artifacts
        self.page_factors = page_factors or {}
        self.page_uuid = str(page_uuid or "")

    def resolve(self, *, factor_ref: str = "", alias: str = "") -> Any:
        from server.services.external_factor_artifacts import factor_by_alias

        wanted_ref = str(factor_ref or "").strip()
        wanted_alias = str(alias or "").strip()
        direct = self.page_factors.get(wanted_ref) or self.page_factors.get(wanted_alias)
        if direct is not None:
            return direct

        matches = [
            record for record in self.records
            if (record["ref"] == wanted_ref if wanted_ref else record["alias"] == wanted_alias)
        ]
        if wanted_ref or self.records:
            if len(matches) != 1:
                target = wanted_ref or wanted_alias
                raise ValueError(f"运行配置不能唯一确定冻结因子: {target}")
            record = matches[0]
            descriptor = require_frozen_factor(record)
            resolved_alias = str(descriptor["alias"] or "").strip()
            external = factor_by_alias(
                self.external_factor_artifacts, resolved_alias,
            )
            if external is not None:
                return external
            from server.modules.shared.factor_param_resolver import (
                resolve_factor_param_value,
            )

            factor_owner = str(descriptor.get("owner_ref") or self.owner).strip()
            return resolve_factor_param_value(
                record,
                username=factor_owner,
                frozen_by_ref=self.frozen_by_ref,
            )

        external = factor_by_alias(self.external_factor_artifacts, wanted_alias)
        if external is not None:
            return external
        from server.services.factor_registry import factor_from_alias

        return factor_from_alias(
            wanted_alias, username=self.owner, page_uuid=self.page_uuid,
        )

    def resolve_refs(self, refs: list[str]) -> list[Any]:
        return [self.resolve(factor_ref=ref) for ref in refs]
