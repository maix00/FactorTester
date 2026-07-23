from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tools.testers.backtest.modules.group_membership import (
    GroupMembershipModule,
)


def products_for_term_carry_signal(
    config: Any,
    signals: Mapping[Any, Any],
) -> tuple[Any, ...]:
    """Use the strategy signal universe, restricted by its fixed mask."""
    products = tuple(signals)
    mask = config.get(GroupMembershipModule.product_mask_names)
    if not mask:
        return products
    allowed = {str(name) for name in mask}
    return tuple(
        product
        for product in products
        if str(getattr(product, "name", product)) in allowed
    )
