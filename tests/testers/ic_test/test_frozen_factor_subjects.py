from __future__ import annotations

import pytest

from tools.testers.ic_test.configuration import CompiledICRunConfiguration

from tests.testers.ic_test.configuration_cases import (
    MOMENTUM_SET,
    ROC,
    SGCCS,
    flat_settings,
    frozen_configuration,
    migrate_and_freeze,
)


def test_factor_set_subject_avoids_a_duplicate_member_manifest() -> None:
    configuration = migrate_and_freeze(
        flat_settings(factor_set_selections=[{"target_ref": MOMENTUM_SET}]),
        {ROC: "1m", SGCCS: "5m"},
        factor_set_members={MOMENTUM_SET: (ROC, SGCCS)},
    )
    assert configuration.factor_subject_refs == (MOMENTUM_SET,)
    assert {item.factor_ref for item in configuration.analysis_graph.core_tests} == {
        ROC,
        SGCCS,
    }
    assert "factor_set_members" not in configuration.to_dict()


def test_standalone_factor_remains_beside_a_factor_set_subject() -> None:
    configuration = migrate_and_freeze(
        flat_settings(factor_set_selections=[{"target_ref": MOMENTUM_SET}]),
        {ROC: "1m", SGCCS: "5m"},
        factor_set_members={MOMENTUM_SET: (ROC,)},
    )
    assert configuration.factor_subject_refs == (MOMENTUM_SET, SGCCS)


def test_factor_set_members_must_be_selected_for_execution() -> None:
    settings = flat_settings(
        factor_selections=[flat_settings()["factor_selections"][0]],
        factor_set_selections=[{"target_ref": MOMENTUM_SET}],
    )
    with pytest.raises(ValueError, match="members are missing from factor_selections"):
        migrate_and_freeze(
            settings,
            {ROC: "1m"},
            factor_set_members={MOMENTUM_SET: (ROC, SGCCS)},
        )


def test_frozen_configuration_rejects_unknown_standalone_subject() -> None:
    payload = frozen_configuration().to_dict()
    payload["factor_subject_refs"] = [
        "factor:v2:fffffffffffffffffffffffffffffffffffffffffff",
    ]
    with pytest.raises(ValueError, match="standalone factor subject"):
        CompiledICRunConfiguration.from_dict(payload)
