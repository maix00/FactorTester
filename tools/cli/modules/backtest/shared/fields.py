"""Backend-registered field resolution for backtest CLI selectors."""

from __future__ import annotations

from dataclasses import dataclass

from tools.cli.field_store import FieldStore


@dataclass(frozen=True, slots=True)
class BacktestPublicFields:
    product_path_candidates: str
    product_path_selection: str
    factor_candidates: str
    factor: str


def resolve_backtest_public_fields(store: FieldStore) -> BacktestPublicFields:
    """Resolve semantic selector fields from the backend manifest.

    CLI commands may expose ergonomic aliases like `--factor`, but the payload
    keys must come from backend-registered public fields.  If a backend stops
    registering a field, selector parsing should fail instead of silently
    inventing a client-side key.
    """
    return BacktestPublicFields(
        product_path_candidates=_require_field(store, "product_path_candidates"),
        product_path_selection=_require_field(store, "product_path_selection"),
        factor_candidates=_require_field(store, "factor_candidates"),
        factor=_require_field(store, "factor"),
    )


def _require_field(store: FieldStore, key: str) -> str:
    if key not in store.defaults:
        raise ValueError(f"后端未注册 backtest public field: {key}")
    return key
