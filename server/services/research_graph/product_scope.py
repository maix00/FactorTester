"""Explicit semantics for the product field on a research graph instance."""

from __future__ import annotations

from typing import Any


def implementation_product_scope(product_group: str) -> dict[str, Any]:
    """Describe the creation-time group without pretending it is a universe.

    A Graph instance needs an implementation group so capability resolution can
    choose the right provider and engine.  The exact traded products, ranking
    universe, and product mask are frozen later in a TrialPlan/RunSpec.
    """
    return {
        "kind": "implementation_product_group",
        "product_group": str(product_group),
        "universe": None,
        "product_mask": None,
        "universe_defined_in": "trial_plan",
    }
