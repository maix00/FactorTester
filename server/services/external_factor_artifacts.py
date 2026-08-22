"""Validation and immutable metadata for external precomputed factor artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.factors.PrecomputedFactorArtifact import PrecomputedFactorArtifact


def _resolve_cn_futures(symbol: str) -> Any | None:
    from sources.LocalCNFutures.CNFutures import CNFutures

    return CNFutures.get_by_product_name(symbol)


def _frozen_descriptor(artifact: PrecomputedFactorArtifact) -> dict[str, Any]:
    """Project one validated artifact into its immutable RunSpec descriptor."""
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


def validate_and_freeze(manifest_path: str) -> dict[str, Any]:
    """Validate the full panel and return the bounded metadata frozen in RunSpec."""
    artifact = PrecomputedFactorArtifact.load(
        Path(manifest_path), product_resolver=_resolve_cn_futures,
    )
    return _frozen_descriptor(artifact)


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


def load_frozen_artifacts(raw: Any) -> list[PrecomputedFactorArtifact]:
    """Revalidate frozen descriptors and return executable factor objects."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ValueError("external_factor_artifacts must be an array")
    loaded: list[PrecomputedFactorArtifact] = []
    seen: set[str] = set()
    for descriptor in raw:
        if not isinstance(descriptor, dict):
            raise ValueError("each external factor artifact must be an object")
        artifact = PrecomputedFactorArtifact.load(
            Path(str(descriptor.get("manifest_path") or "")),
            product_resolver=_resolve_cn_futures,
        )
        current = _frozen_descriptor(artifact)
        for field in ("artifact_id", "manifest_sha256", "factor_sha256"):
            if str(descriptor.get(field) or "") != str(current[field]):
                raise ValueError(f"external factor artifact {field} changed after submission")
        if artifact.alias in seen:
            raise ValueError(f"duplicate external factor alias: {artifact.alias}")
        seen.add(artifact.alias)
        loaded.append(artifact)
    return loaded


def factor_by_alias(raw: Any, alias: str) -> PrecomputedFactorArtifact | None:
    matches = [factor for factor in load_frozen_artifacts(raw) if factor.alias == alias]
    if len(matches) > 1:
        raise ValueError(f"ambiguous external factor alias: {alias}")
    return matches[0] if matches else None


def result_metadata(raw: Any) -> list[dict[str, str]]:
    """Return bounded provenance suitable for durable result metadata."""
    return [
        {
            "artifact_id": str(item["artifact_id"]),
            "alpha_id": str(item["alpha_id"]),
            "manifest_sha256": str(item["manifest_sha256"]),
            "factor_sha256": str(item["factor_sha256"]),
        }
        for item in (raw or [])
        if isinstance(item, dict)
    ]
