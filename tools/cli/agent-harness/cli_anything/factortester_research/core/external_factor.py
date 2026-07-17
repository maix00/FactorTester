from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def vibe_pipeline_plan(
    *, integration_root: str, data_root: str, alpha_id: str,
    dataset_version: str = "v1",
) -> list[dict[str, Any]]:
    root = Path(integration_root).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    python = root / ".conda" / "bin" / "python"
    daily = root / "data" / "processed" / "china_futures_daily" / dataset_version
    minute = root / "data" / "processed" / "china_futures_minute" / dataset_version
    factor = root / "artifacts" / "factors" / alpha_id
    return [
        {
            "phase": "build_daily_panel",
            "argv": [
                str(python),
                str(root / "adapters/data_prep/build_china_futures_panel.py"),
                "--source-dir", str(data / "main_dayk"),
                "--output-dir", str(daily),
            ],
            "output_manifest": str(daily / "manifest.json"),
        },
        {
            "phase": "build_minute_panel",
            "argv": [
                str(python),
                str(root / "adapters/data_prep/build_china_futures_minute_panel.py"),
                "--source-dir", str(data / "main_mink"),
                "--output-dir", str(minute),
            ],
            "output_manifest": str(minute / "manifest.json"),
        },
        {
            "phase": "compute_vibe_daily_factor",
            "argv": [
                str(python),
                str(root / "adapters/vibe_factors/bridge.py"),
                "compute", "--alpha", alpha_id,
                "--input", str(daily / "bars_long.parquet"),
                "--output-dir", str(factor),
                "--allow-cross-market",
            ],
            "output_manifest": str(factor / "manifest.json"),
        },
        {
            "phase": "validate_external_artifacts",
            "dataset_manifests": [
                str(daily / "manifest.json"), str(minute / "manifest.json"),
            ],
            "factor_manifests": [str(factor / "manifest.json")],
        },
        {
            "phase": "gtht_handoff",
            "status": "platform_gap",
            "reason": (
                "GTHT currently has no public CLI/HTTP contract for importing a "
                "precomputed date-by-product factor panel as a FactorRunResult. "
                "Do not bypass FactorExpr/signal alignment or native replay."
            ),
        },
    ]


def _read_manifest(path: str) -> tuple[Path, dict[str, Any]]:
    manifest_path = Path(path).expanduser().resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"manifest must be an object: {manifest_path}")
    return manifest_path, payload


def validate_dataset_manifest(path: str) -> dict[str, Any]:
    manifest_path, payload = _read_manifest(path)
    required = {"schema_version", "rows", "symbols", "timing"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"dataset manifest missing: {sorted(missing)}")
    timing = payload.get("timing") or {}
    if timing.get("earliest_execution") != "next_bar":
        raise ValueError("dataset manifest must require next_bar execution")
    if int(payload["rows"]) <= 0 or int(payload["symbols"]) <= 0:
        raise ValueError("dataset manifest rows and symbols must be positive")
    return {
        "kind": "dataset", "path": str(manifest_path), "valid": True,
        "frequency": payload.get("frequency", "1d"),
        "rows": int(payload["rows"]), "symbols": int(payload["symbols"]),
    }


def validate_factor_manifest(path: str) -> dict[str, Any]:
    manifest_path, payload = _read_manifest(path)
    required = {
        "schema_version", "alpha_id", "research_status", "input", "output",
        "timing",
    }
    missing = required - set(payload)
    if missing:
        raise ValueError(f"factor manifest missing: {sorted(missing)}")
    timing = payload.get("timing") or {}
    if timing.get("earliest_execution") != "next_bar":
        raise ValueError("factor manifest must require next_bar execution")
    if payload.get("research_status") != "experimental_unvalidated":
        raise ValueError("cross-market Vibe factor must remain experimental_unvalidated")
    output = payload.get("output") or {}
    if int(output.get("finite_observations") or 0) <= 0:
        raise ValueError("factor manifest has no finite observations")
    return {
        "kind": "factor", "path": str(manifest_path), "valid": True,
        "alpha_id": str(payload["alpha_id"]),
        "finite_observations": int(output["finite_observations"]),
    }
