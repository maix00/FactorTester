"""Preflight checks for client-owned local test runs."""

from __future__ import annotations

from typing import Any

from tools.cli.local_sources.contracts import LocalSourceManifest


class LocalRunRequirementsError(ValueError):
    """Raised when a local run requests data unavailable on this device."""

    def __init__(self, message: str, *, missing: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.missing = missing


def validate_local_run_requirements(
    manifests: tuple[LocalSourceManifest, ...] | list[LocalSourceManifest],
    requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check product/frequency coverage before a local engine is started."""
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("local run requirements must be a non-empty list")
    available: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for raw in requirements:
        if not isinstance(raw, dict):
            raise ValueError("each local run requirement must be an object")
        product_ref = str(
            raw.get("product_ref") or raw.get("product") or raw.get("alias") or ""
        ).strip()
        frequency = str(raw.get("frequency") or "").strip()
        if not product_ref:
            raise ValueError("local run requirement product_ref is required")
        matches: list[dict[str, Any]] = []
        for manifest in manifests:
            product = next(
                (
                    item for item in manifest.products
                    if product_ref in {item.product_ref, item.alias}
                    or str(item.metadata.get("code") or "").strip() == product_ref
                ),
                None,
            )
            if product is None:
                continue
            ready = manifest.availability.get("status") == "ready"
            available_refs = set(
                manifest.availability.get("available_product_refs") or ()
            )
            if product.product_ref not in available_refs:
                continue
            modes = [
                dict(member["data_mode"])
                for member in manifest.members
                if member["data_mode"].get("available", True) is not False
            ]
            matching_modes = [
                mode for mode in modes
                if not frequency or str(mode.get("frequency") or "") == frequency
            ]
            if ready and matching_modes:
                matches.append({
                    "source_id": manifest.source_id,
                    "source_name": manifest.source_name,
                    "product_ref": product.product_ref,
                    "frequency": frequency,
                    "data_modes": [
                        str(mode.get("id") or "") for mode in matching_modes
                    ],
                })
        if matches:
            available.extend(matches)
        else:
            missing.append({
                "product_ref": product_ref,
                "frequency": frequency,
                "reason": "local data source does not provide this product/frequency",
            })
    result = {
        "valid": not missing,
        "requirements": requirements,
        "available": available,
        "missing": missing,
    }
    if missing:
        raise LocalRunRequirementsError(
            "本地数据源缺少运行所需的产品或数据频率", missing=missing,
        )
    return result


__all__ = ["LocalRunRequirementsError", "validate_local_run_requirements"]
