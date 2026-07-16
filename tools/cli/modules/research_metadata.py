"""Helpers for attaching structured research metadata to saved runs."""

from __future__ import annotations

from typing import Any


RESEARCH_META_KEYS = ("sample_role", "regime_label", "slice_name")
RESEARCH_AUDIT_KEYS = (
    "test_count",
    "grid_size",
    "oos_pass",
    "multi_product_group_pass",
    "costed_pass",
)


def research_metadata_from_settings(*sources: dict[str, Any] | None) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        nested = source.get("research_meta")
        if isinstance(nested, dict):
            _merge_research_metadata(meta, nested)
        _merge_research_metadata(meta, source)
    return meta


def attach_research_metadata(
    payload: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = research_metadata_from_settings(settings, config, extra)
    if not meta:
        return payload
    payload_config = payload.setdefault("config", {})
    if not isinstance(payload_config, dict):
        payload_config = {}
        payload["config"] = payload_config
    payload_config["research_meta"] = meta
    for key in RESEARCH_META_KEYS:
        if meta.get(key) not in (None, ""):
            payload[key] = str(meta[key])
    payload_metrics = payload.setdefault("metrics", {})
    if not isinstance(payload_metrics, dict):
        payload_metrics = {}
        payload["metrics"] = payload_metrics
    for key in RESEARCH_AUDIT_KEYS:
        if meta.get(key) not in (None, ""):
            payload_metrics.setdefault(key, meta[key])
    if metrics:
        for key, value in metrics.items():
            if value is not None:
                payload_metrics.setdefault(key, value)
    return payload


def _merge_research_metadata(out: dict[str, Any], source: dict[str, Any]) -> None:
    for key in (*RESEARCH_META_KEYS, *RESEARCH_AUDIT_KEYS):
        value = source.get(key)
        if value not in (None, ""):
            out[key] = value
