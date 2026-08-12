from __future__ import annotations

import pytest

from tools.cli.commands.research_graph_obligation_context import (
    refresh_context_metadata,
)
from tools.cli.release.research_obligations import (
    initialize_ledger,
)


def _ledger() -> dict:
    return initialize_ledger(
        branch_ref="graph-branch:instance:branch",
        graph_ref="factor-research@v10",
        current_node="data_contract",
        context_ref="sha256:old",
        checkpoint_ref="trace:one",
        obligations=[{
            "obligation_id": "data-contract",
            "status": "bounded",
            "requirement_refs": ["data.temporal_coverage"],
        }],
    )


def _expected() -> dict[str, str]:
    return {
        "branch_ref": "graph-branch:instance:branch",
        "graph_ref": "factor-research@v10",
        "current_node": "data_contract",
        "context_ref": "sha256:new",
        "checkpoint_ref": "trace:one",
    }


def test_report_only_context_drift_is_refreshed_without_an_event() -> None:
    ledger = refresh_context_metadata(
        _ledger(), expected_branch=_expected(),
    )

    assert ledger["branch"]["context_ref"] == "sha256:new"
    assert ledger["generation"] == 0
    assert ledger["history"] == []


def test_context_refresh_rejects_node_or_checkpoint_drift() -> None:
    expected = _expected()
    expected["current_node"] = "factor_semantics"

    with pytest.raises(ValueError, match="branch/node/checkpoint is stale"):
        refresh_context_metadata(
            _ledger(), expected_branch=expected,
        )


def test_context_refresh_preserves_local_projection_ahead_of_server() -> None:
    ledger = _ledger()
    refreshed = refresh_context_metadata(
        ledger, expected_branch=_expected(),
    )

    assert refreshed["current_projection"] == ledger["current_projection"]


def test_context_refresh_does_not_mutate_persisted_value() -> None:
    ledger = _ledger()

    refresh_context_metadata(ledger, expected_branch=_expected())

    assert ledger["branch"]["context_ref"] == "sha256:old"
