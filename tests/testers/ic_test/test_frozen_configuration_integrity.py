from __future__ import annotations

import pytest

from tools.testers.ic_test.configuration import CompiledICRunConfiguration

from tests.testers.ic_test.configuration_cases import ROC, frozen_configuration


def test_frozen_configuration_round_trips() -> None:
    configuration = frozen_configuration()
    restored = CompiledICRunConfiguration.from_dict(configuration.to_dict())
    assert restored == configuration
    assert restored.configuration_ref == configuration.configuration_ref


def test_frozen_configuration_rejects_tampered_core_identity() -> None:
    payload = frozen_configuration().to_dict()
    payload["analysis_graph"]["core_tests"][0]["horizon"] = "DAY99"
    with pytest.raises(ValueError, match="core_test_ref does not match"):
        CompiledICRunConfiguration.from_dict(payload)


def test_frozen_configuration_rejects_incomplete_job_partitions() -> None:
    payload = frozen_configuration().to_dict()
    next(iter(payload["job_partitions"].values())).pop()
    with pytest.raises(ValueError, match="job partitions must contain every core test"):
        CompiledICRunConfiguration.from_dict(payload)


def test_frozen_configuration_rejects_disagreeing_horizon_resolution() -> None:
    payload = frozen_configuration().to_dict()
    request_ref = payload["authoring_core_tests"][0]["request_ref"]
    payload["resolved_horizons_by_request"][request_ref][ROC][0][
        "physical_frequency"
    ] = "DAY99"
    with pytest.raises(ValueError, match="resolved horizons do not match"):
        CompiledICRunConfiguration.from_dict(payload)


def test_frozen_configuration_rejects_tampered_horizon_authorship() -> None:
    payload = frozen_configuration(forward_return_horizons={
        "sampling": "explicit",
        "bases": ["signal"],
        "multipliers": [1, 3],
    }).to_dict()
    payload["authoring_core_tests"][0]["horizon"]["multipliers"] = [7]
    with pytest.raises(ValueError, match="request_ref does not match"):
        CompiledICRunConfiguration.from_dict(payload)
