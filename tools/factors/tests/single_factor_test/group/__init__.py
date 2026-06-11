"""Flat group definition for FactorTester grouped backtests.

A ``_FactorGroupTestGroup`` is the atomic unit of a group configuration.
Every group that the user wants to simulate is a separate, independent instance
in a flat list.

Groups with ``product_list=None`` are "identity" groups: their membership is an
exact copy of the membership row computed from the (tester, factor, n_groups) triple.

Groups with ``product_list`` are "screened" groups: their membership is the same
row filtered to only those products, i.e. the intersection of the identity row
and the product set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True)
class _FactorGroupTestGroup:
    """A single group within a grouped factor backtest.

    Attributes
    ----------
    tester_id : str
        Identifies the FactorTester instance (corresponds to a submission).
    factor_alias : str
        Factor name (e.g. ``MmRet``).
    n_groups : int
        Total number of groups the membership was bucketed into.
    group_index : int
        Local 0-based index into the (T, n_groups, P) membership array.
    key : str
        Display key (short identifier) for this group.
    name : str
        Human-readable display name for this group.
    product_list : list[str] | None
        Product names to filter this group to. ``None`` means no filtering
        (the group inherits the full product universe of its membership row).
        When non-empty, the membership is the intersection of the base row
        with this product set.
    fee_modifications : list | None
        Per-group fee modifications (FeeModification objects serialized as dicts).
    fee_mode : str | None
        Fee mode override for this group.
    fee_rate : float | None
        Uniform fee rate override for this group.
    use_close_today : bool | None
        Close-today override for this group.
    rebalance_mode : str | None
        Rebalance mode override for this group.
    liquidity_mode : str | None
        Liquidity mode override for this group.
    liquidity_percent : float | None
        Liquidity percentage override for this group.
    margin_mode : str | None
        Margin mode override for this group.
    """

    # ── Identity ──
    tester_id: str
    factor_alias: str
    n_groups: int
    group_index: int
    key: str
    name: str

    # ── Product filtering ──
    product_list: Optional[list[str]] = None

    # ── Fee / config overrides ──
    fee_modifications: Optional[list] = None
    fee_mode: Optional[str] = None
    fee_rate: Optional[float] = None
    use_close_today: Optional[bool] = None
    rebalance_mode: Optional[str] = None
    liquidity_mode: Optional[str] = None
    liquidity_percent: Optional[float] = None
    margin_mode: Optional[str] = None

    # ── Display ──
    _id: Optional[str] = field(default=None, compare=False)

    @property
    def triple_key(self) -> tuple[str, str, int]:
        """Unique key for deduplication: (tester_id, factor_alias, n_groups)."""
        return (self.tester_id, self.factor_alias, self.n_groups)

    @property
    def is_screened(self) -> bool:
        """True when this group has a product filter list."""
        return bool(self.product_list)
