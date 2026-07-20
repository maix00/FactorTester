"""Strict external precomputed-factor artifact contract.

The artifact is deliberately a read-only factor-like object.  It enters the
existing PRE_REPLAY path through ``evaluate`` but never claims to be a
``FactorExpr`` or to support incremental execution.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from tools.data.types import DataFreq
from tools.data.types.time_index import DataIndex
from tools.factors.FactorRunResult import FactorRunResult


ProductResolver = Mapping[str, Any] | Callable[[str], Any | None]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(manifest_path: Path, raw: Any) -> Path:
    path = Path(str(raw or "")).expanduser()
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path.resolve()


def _resolve_product(resolver: ProductResolver, symbol: str) -> Any | None:
    if callable(resolver):
        return resolver(symbol)
    return resolver.get(symbol)


@dataclass(frozen=True, slots=True, eq=False)
class PrecomputedFactorArtifact:
    alpha_id: str
    signals: pd.DataFrame
    data_present_mask: pd.DataFrame
    provenance: Mapping[str, Any]
    freq: DataFreq = DataFreq.DAY1

    @classmethod
    def load(cls, manifest: str | Path, *, product_resolver: ProductResolver) -> "PrecomputedFactorArtifact":
        manifest_path = Path(manifest).expanduser().resolve()
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("precomputed factor manifest must be a JSON object")
        required = {"schema_version", "status", "alpha_id", "factor", "timing", "research"}
        missing = required - set(payload)
        if missing:
            raise ValueError(f"precomputed factor manifest missing: {sorted(missing)}")
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported precomputed factor schema_version")
        if payload.get("status") != "ready_for_gtht_import_contract":
            raise ValueError("precomputed factor artifact is not ready for GTHT import")
        timing = payload.get("timing") or {}
        if timing.get("information_time") != "daily_bar_close":
            raise ValueError("v1 precomputed factor requires information_time=daily_bar_close")
        if timing.get("execution") != "next_bar":
            raise ValueError("precomputed factor requires next_bar execution")
        if not timing.get("same_close_execution_forbidden"):
            raise ValueError("precomputed factor must forbid same-close execution")
        research = payload.get("research") or {}
        if research.get("status") != "experimental_unvalidated":
            raise ValueError("cross-market factor must remain experimental_unvalidated")

        factor = payload.get("factor") or {}
        factor_path = _resolve_path(manifest_path, factor.get("path"))
        if not factor_path.is_file():
            raise FileNotFoundError(f"precomputed factor parquet not found: {factor_path}")
        expected_hash = str(factor.get("sha256") or "")
        actual_hash = _sha256(factor_path)
        if not expected_hash or actual_hash != expected_hash:
            raise ValueError("precomputed factor parquet hash mismatch")

        signals = pd.read_parquet(factor_path)
        if signals.empty:
            raise ValueError("precomputed factor contains no signal rows")
        if not isinstance(signals.index, pd.DatetimeIndex):
            raise ValueError("precomputed factor index must be a DatetimeIndex")
        if signals.index.tz is not None:
            raise ValueError("daily trading-day factor index must be timezone-naive")
        if not signals.index.is_unique or not signals.index.is_monotonic_increasing:
            raise ValueError("factor timestamps must be unique and monotonic")
        if not signals.index.equals(signals.index.normalize()):
            raise ValueError("daily trading-day factor index must be normalized to midnight")
        if not signals.columns.is_unique:
            raise ValueError("factor symbols must be unique")

        resolved: list[Any] = []
        unknown: list[str] = []
        for raw_symbol in signals.columns:
            symbol = str(raw_symbol)
            product = _resolve_product(product_resolver, symbol)
            if product is None:
                unknown.append(symbol)
            resolved.append(product)
        if unknown:
            raise ValueError(f"unknown GTHT products in factor artifact: {sorted(unknown)}")
        if len(set(resolved)) != len(resolved):
            raise ValueError("multiple external symbols resolve to the same GTHT product")

        numeric = signals.apply(pd.to_numeric, errors="coerce").astype("float64")
        values = numeric.to_numpy()
        if np.isinf(values).any():
            raise ValueError("precomputed factor contains infinity")
        if not np.isfinite(values).any():
            raise ValueError("precomputed factor contains no finite observations")
        numeric.columns = resolved
        present = numeric.notna()
        provenance = {
            "kind": "precomputed_factor_artifact",
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256(manifest_path),
            "factor_path": str(factor_path),
            "factor_sha256": actual_hash,
            "alpha_id": str(payload["alpha_id"]),
            "research_status": str(research["status"]),
            "information_time": str(timing["information_time"]),
            "execution": str(timing["execution"]),
        }
        return cls(
            alpha_id=str(payload["alpha_id"]),
            signals=numeric,
            data_present_mask=present,
            provenance=provenance,
        )

    @property
    def alias(self) -> str:
        return self.alpha_id

    @property
    def name(self) -> str:
        return self.alpha_id

    def supports_vectorized(self) -> bool:
        return True

    def supports_incremental(self) -> bool:
        return False

    def backtest_factor_cache_key(self) -> tuple[str, str, str]:
        return (
            "precomputed_factor_artifact",
            self.alpha_id,
            str(self.provenance["factor_sha256"]),
        )

    def _structural_key(self) -> tuple[str, str, str]:
        """Expose the stable identity expected by IC grouping."""
        return self.backtest_factor_cache_key()

    def __iter__(self):
        """Let legacy FactorTester treat this factor-like object as one item."""
        yield self

    def __len__(self) -> int:
        return 1

    def evaluate(self, *args: Any, start_dt: Any = None, end_dt: Any = None, **kwargs: Any) -> pd.DataFrame:
        table = self.signals
        if start_dt is not None and end_dt is not None:
            start = _normalized_bound(start_dt)
            end = _normalized_bound(end_dt)
            table = table.loc[(table.index >= start) & (table.index <= end)]
        evaluated = table.copy()
        from tools.factors.FactorTester import _active_tester

        tester = _active_tester.get()
        if tester is not None:
            result = tester._get_result(self)
            imported = self.to_run_result(table=evaluated)
            result.source_table = imported.source_table
            result.table = imported.table
            result.data_present_mask = imported.data_present_mask
            result.data_present_all = imported.data_present_all
            result.provenance = imported.provenance
        return evaluated

    def align_to_market_schedule(self, schedule: pd.DataFrame) -> pd.DataFrame:
        """Map trading-day values onto GTHT's actual causal SIGNAL index."""
        days = DataIndex(schedule.index).trading_day_index()
        if days.duplicated().any():
            raise ValueError("GTHT signal schedule contains duplicate trading days")
        aligned = self.signals.reindex(days)
        aligned.index = schedule.index
        return aligned

    def to_run_result(self, table: pd.DataFrame | None = None) -> FactorRunResult:
        result = FactorRunResult()
        result.source_table = self.signals
        result.table = self.signals if table is None else table
        result.data_present_mask = result.table.notna()
        result.data_present_all = bool(result.data_present_mask.to_numpy().all())
        result.provenance = dict(self.provenance)
        return result


def _normalized_bound(value: Any) -> pd.Timestamp:
    raw = getattr(value, "ts", value)
    timestamp = pd.Timestamp(raw)
    if timestamp.tz is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp.normalize()
