from __future__ import annotations

import pytest

from tools.testers.ic_test.configuration import migrate_flat_ic_settings

from tests.testers.ic_test.configuration_cases import (
    ROC,
    SGCCS,
    flat_settings,
    frozen_configuration,
    migrate_and_freeze,
)


def test_flat_core_fields_migrate_to_factor_specific_physical_horizons() -> None:
    configuration = frozen_configuration()
    cores = configuration.analysis_graph.core_tests

    assert {item.product_scope_ref for item in cores} == {"day", "night"}
    assert {item.method for item in cores} == {"rank", "pearson"}
    assert {item.entry_delay_bars for item in cores} == {0, 1}
    assert "DAY1" in {item.horizon for item in cores if item.factor_ref == ROC}
    assert any(item.factor_ref == ROC and item.horizon == "MIN1" for item in cores)
    assert any(item.factor_ref == SGCCS and item.horizon == "MIN5" for item in cores)
    assert set(configuration.job_partitions) == {"day", "night"}
    resolved = configuration.resolved_horizons_by_request[
        configuration.authoring_core_tests[0].request_ref
    ]
    assert resolved[ROC][0].to_dict() == {
        "physical_frequency": "MIN1",
        "origins": [{"base": "signal", "multiplier": 1}],
    }
    assert resolved[SGCCS][0].to_dict() == {
        "physical_frequency": "MIN5",
        "origins": [{"base": "signal", "multiplier": 1}],
    }


def test_frozen_identity_includes_core_and_analysis_semantics() -> None:
    refs = {
        frozen_configuration().configuration_ref,
        frozen_configuration(ic_correlation="pearson").configuration_ref,
        frozen_configuration(
            return_price_basis="next_close_to_close_adjusted",
        ).configuration_ref,
        frozen_configuration(rolling_window=60).configuration_ref,
    }
    assert len(refs) == 4


def test_flat_migration_is_order_independent_and_emits_no_flat_fields() -> None:
    left = frozen_configuration()
    right = migrate_and_freeze(
        flat_settings(
            factor_selections=list(reversed(flat_settings()["factor_selections"])),
            product_path_selections=list(
                reversed(flat_settings()["product_path_selections"]),
            ),
            ic_lags=[1, 0, 1],
        ),
        {SGCCS: "5m", ROC: "1m"},
    )

    assert left.configuration_ref == right.configuration_ref
    payload = left.to_dict()
    assert "factor_selections" not in payload
    assert "ic_decay_lags" not in payload
    assert "rolling_window" not in payload


def test_flat_migration_rejects_unfrozen_and_unimplemented_inputs() -> None:
    assert frozen_configuration(min_cross_section_count=5).analysis_graph.core_tests
    with pytest.raises(ValueError, match="factor:v2 formula reference"):
        migrate_flat_ic_settings(
            flat_settings(factor_selections=[{"factor_alias": "ROC"}]),
            factor_frequencies={ROC: "1m"},
        )
    for key in ("group_adjust", "by_group"):
        with pytest.raises(ValueError, match=f"{key} is not executable"):
            frozen_configuration(**{key: "on"})
    with pytest.raises(ValueError, match="min_cross_section_count is not executable"):
        frozen_configuration(min_cross_section_count=10)
