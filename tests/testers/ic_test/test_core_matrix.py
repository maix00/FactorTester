from __future__ import annotations

import pytest

from tools.testers.ic_test.core import (
    ICCoreTest,
    ICCoreTestBlock,
    expand_core_test_blocks,
)


def _block(**overrides: object) -> ICCoreTestBlock:
    values = {
        "product_scope_refs": ("metals",),
        "factor_refs": ("factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY",),
        "horizons": ("MIN5",),
        "entry_delay_bars": (0,),
        "methods": ("rank",),
        "return_price_basis": "next_open_to_open_adjusted",
    }
    values.update(overrides)
    return ICCoreTestBlock(**values)


def test_batch_expansion_is_explicit_and_reports_real_cell_count() -> None:
    block = _block(
        factor_refs=("factor:v2:xQnmUW0nlPh8kkSw5bkf1i42P5zJd2jACBY4WgOMeZo", "factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY"),
        horizons=("MIN10", "MIN5"),
        entry_delay_bars=(1, 0),
    )

    assert block.cell_count == 8
    assert block.to_dict()["expansion"] == "explicit_cartesian"
    assert len(block.expand()) == 8


def test_batch_identity_ignores_selection_order_and_duplicates() -> None:
    left = _block(
        factor_refs=("factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY", "factor:v2:xQnmUW0nlPh8kkSw5bkf1i42P5zJd2jACBY4WgOMeZo", "factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY"),
        horizons=("MIN5", "MIN10"),
    )
    right = _block(
        factor_refs=("factor:v2:xQnmUW0nlPh8kkSw5bkf1i42P5zJd2jACBY4WgOMeZo", "factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY"),
        horizons=("MIN10", "MIN5"),
    )

    assert left.block_ref == right.block_ref
    assert [item.core_test_ref for item in left.expand()] == [
        item.core_test_ref for item in right.expand()
    ]


def test_overlapping_blocks_deduplicate_cells_in_canonical_order() -> None:
    broad = _block(horizons=("MIN5", "MIN10"))
    duplicate = _block(horizons=("MIN5",))

    cells = expand_core_test_blocks((duplicate, broad))

    assert len(cells) == 2
    assert [cell.core_test_ref for cell in cells] == sorted(
        cell.core_test_ref for cell in cells
    )


def test_expansion_limit_rejects_accidental_large_cartesian_product() -> None:
    block = _block(
        product_scope_refs=("metals", "energy"),
        factor_refs=("factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY", "factor:v2:xQnmUW0nlPh8kkSw5bkf1i42P5zJd2jACBY4WgOMeZo"),
        horizons=("MIN1", "MIN5", "MIN10"),
    )

    with pytest.raises(ValueError, match="expands to 12 cells; maximum is 10"):
        block.expand(maximum_cells=10)


def test_core_test_rejects_boolean_or_fractional_delay() -> None:
    base = {
        "product_scope_ref": "metals",
        "factor_ref": "factor:v2:C_hxmG_kcqe_YUpCZtfvY7cvSxHKmqFz1vC8-DpM0hY",
        "horizon": "MIN5",
        "method": "rank",
        "return_price_basis": "next_open_to_open_adjusted",
    }

    with pytest.raises(ValueError, match="non-negative integer"):
        ICCoreTest(entry_delay_bars=True, **base)
    with pytest.raises(ValueError, match="non-negative integer"):
        ICCoreTest(entry_delay_bars=1.5, **base)
