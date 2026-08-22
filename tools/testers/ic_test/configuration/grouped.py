"""Typed schema-2 IC configuration-group compiler."""
from __future__ import annotations
import hashlib, json
from collections.abc import Mapping
from typing import Any
from .authoring import ICRunAuthoringConfiguration
from .authoring.freezer import freeze_ic_run_configuration

def compile_ic_grouped_configuration(value: dict[str, Any], *, factor_frequencies: dict[str, Any] | None = None) -> dict[str, Any]:
    groups = value.get("configuration_groups")
    if not isinstance(groups, list) or len(groups) != 1:
        raise ValueError("Slice 1 requires exactly one configuration group")
    if not isinstance(factor_frequencies, Mapping) or not factor_frequencies:
        raise ValueError("frozen factor frequency descriptors are required")
    authoring = ICRunAuthoringConfiguration.from_dict({"schema_version": 2, "configuration_groups": groups})
    compiled = freeze_ic_run_configuration(authoring, factor_frequencies=factor_frequencies)
    encoded = compiled.to_dict()
    ordered = sorted(groups, key=lambda item: str(item.get("config_group_id") or ""))
    provenance = [{"config_group_id": str(item["config_group_id"]), "product_scope_ref": str(item["product_scope_ref"]), "factor_ref": str(item["factor_ref"]), "core_ref": authoring.core_tests[index].request_ref} for index, item in enumerate(ordered)]
    encoded["group_provenance"] = provenance
    encoded["compiled_config_hash"] = hashlib.sha256(json.dumps(encoded, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    encoded["provenance"] = provenance[0] if len(provenance) == 1 else {"groups": provenance}
    return {"groups": provenance, **encoded}
