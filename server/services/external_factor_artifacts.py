"""Validation and immutable metadata for external precomputed factor artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.factors.PrecomputedFactorArtifact import PrecomputedFactorArtifact


def _resolve_cn_futures(symbol: str) -> Any | None:
    from sources.LocalCNFutures.CNFutures import CNFutures

    return CNFutures.get_by_product_name(symbol)


def validate_and_freeze(manifest_path: str) -> dict[str, Any]:
    """Validate the full panel and return the bounded metadata frozen in RunSpec."""
    artifact = PrecomputedFactorArtifact.load(
        Path(manifest_path), product_resolver=_resolve_cn_futures,
    )
    provenance = dict(artifact.provenance)
    return {
        "artifact_id": (
            f"{artifact.alpha_id}:"
            f"{str(provenance['factor_sha256'])[:16]}"
        ),
        "kind": "precomputed_factor_artifact",
        "alpha_id": artifact.alpha_id,
        "manifest_path": str(provenance["manifest_path"]),
        "manifest_sha256": str(provenance["manifest_sha256"]),
        "factor_path": str(provenance["factor_path"]),
        "factor_sha256": str(provenance["factor_sha256"]),
        "information_time": str(provenance["information_time"]),
        "execution": str(provenance["execution"]),
        "research_status": str(provenance["research_status"]),
        "rows": int(artifact.signals.shape[0]),
        "products": int(artifact.signals.shape[1]),
        "finite_observations": int(artifact.data_present_mask.to_numpy().sum()),
    }


def freeze_configured_artifacts(shared: dict[str, Any]) -> list[dict[str, Any]]:
    raw = shared.get("external_factor_artifacts") or []
    if not isinstance(raw, list):
        raise ValueError("shared.external_factor_artifacts must be an array")
    frozen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each external factor artifact must be an object")
        manifest_path = str(item.get("manifest_path") or "").strip()
        if not manifest_path:
            raise ValueError("external factor artifact requires manifest_path")
        current = validate_and_freeze(manifest_path)
        for field in ("artifact_id", "manifest_sha256", "factor_sha256"):
            declared = str(item.get(field) or "")
            if declared and declared != str(current[field]):
                raise ValueError(f"external factor artifact {field} changed")
        artifact_id = str(current["artifact_id"])
        if artifact_id in seen:
            raise ValueError(f"duplicate external factor artifact: {artifact_id}")
        seen.add(artifact_id)
        frozen.append(current)
    return frozen
