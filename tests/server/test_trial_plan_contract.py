"""TrialPlan schema, hash, and graph-trace freeze tests."""

from __future__ import annotations

import orjson
import pytest

import settings as Settings
from server.services.research_graph.branch.transition import (
    advance_graph_branch,
)
from server.services.research_graph.trial_plan import (
    canonical_trial_plan,
    prepare_trial_plan_evidence,
    trial_plan_hash,
    validate_trial_plan_transition,
)
from tests.server.trial_plan_fixtures import (
    initialize_branch,
    initialize_graph_version,
    trial_plan,
)
from tools.data.sqlite.db import connect_sqlite


def test_trial_plan_hash_is_canonical_and_source_free() -> None:
    plan = trial_plan("a" * 64)
    reordered = dict(reversed(list(plan.items())))

    assert canonical_trial_plan(reordered) == canonical_trial_plan(plan)
    assert trial_plan_hash(reordered) == trial_plan_hash(plan)
    with pytest.raises(ValueError, match="unsupported fields"):
        canonical_trial_plan({**plan, "factor_source": "secret.py"})
    private_path = {
        **plan,
        "stopping": {
            **plan["stopping"],
            "parameters": {"rationale_path": "/Users/alice/private.md"},
        },
    }
    with pytest.raises(ValueError, match="private local path"):
        canonical_trial_plan(private_path)
    hidden_source = {
        **plan,
        "stopping": {
            **plan["stopping"],
            "parameters": {"formula": "private factor expression"},
        },
    }
    with pytest.raises(ValueError, match="private/source fields"):
        canonical_trial_plan(hidden_source)


def test_trial_plan_rejects_sample_stopping_and_runspec_mismatches() -> None:
    plan = trial_plan("a" * 64)
    cross_role = {
        **plan,
        "sample_roles": [
            *plan["sample_roles"],
            {
                "sample_ref": "holdout-2024",
                "sample_hash": "d" * 64,
                "role": "holdout",
                "run_spec_hashes": ["a" * 64],
            },
        ],
    }
    with pytest.raises(ValueError, match="cannot cross TrialPlan sample roles"):
        canonical_trial_plan(cross_role)
    distinct_slice = {
        **cross_role["sample_roles"][1],
        "sample_hash": "e" * 64,
    }
    canonical_trial_plan({
        **plan,
        "sample_roles": [*plan["sample_roles"], distinct_slice],
    })
    unknown_outcome = {
        **plan,
        "stopping": {
            **plan["stopping"],
            "monitored_outcomes": ["unplanned-sharpe"],
        },
    }
    with pytest.raises(ValueError, match="undeclared outcomes"):
        canonical_trial_plan(unknown_outcome)
    unplanned_run = {
        **plan,
        "comparisons": [{
            "comparison_id": "main-comparison",
            "members": [{
                "run_spec_hash": "b" * 64,
                "trial_role": "main-only",
            }],
        }],
    }
    with pytest.raises(ValueError, match="no declared sample role"):
        canonical_trial_plan(unplanned_run)


def test_transition_freezes_one_body_then_accepts_only_matching_hash() -> None:
    plan = trial_plan("a" * 64)
    prepared, plan_hash, has_body = prepare_trial_plan_evidence({
        "trial_plan": plan,
    })

    assert prepared["trial_plan_hash"] == plan_hash == trial_plan_hash(plan)
    assert validate_trial_plan_transition(
        current_hash="",
        proposed_hash=plan_hash,
        has_body=has_body,
    ) == plan_hash
    assert validate_trial_plan_transition(
        current_hash=plan_hash,
        proposed_hash=plan_hash,
        has_body=False,
    ) == plan_hash
    with pytest.raises(ValueError, match="already persisted"):
        validate_trial_plan_transition(
            current_hash=plan_hash,
            proposed_hash=plan_hash,
            has_body=True,
        )
    with pytest.raises(ValueError, match="new immutable body"):
        validate_trial_plan_transition(
            current_hash=plan_hash,
            proposed_hash="b" * 64,
            has_body=False,
        )


def test_graph_transition_persists_one_canonical_plan_body(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "transition.sqlite"
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", path)
    plan = trial_plan("a" * 64)
    plan_hash = trial_plan_hash(plan)
    initialize_branch(path, "")
    initialize_graph_version(path)

    advanced = advance_graph_branch(
        instance_id="instance-1",
        branch_id="branch-1",
        owner="alice",
        edge_id="freeze-plan",
        evidence={"trial_plan": plan},
    )

    assert advanced["current_node"] == "diagnostics"
    with connect_sqlite(path) as conn:
        branch = conn.execute(
            """
            SELECT current_trial_plan_hash
            FROM research_graph_branches
            WHERE branch_id='branch-1'
            """
        ).fetchone()
        trace = conn.execute(
            """
            SELECT evidence_json FROM research_graph_trace
            WHERE branch_id='branch-1'
            """
        ).fetchone()
    evidence = orjson.loads(trace["evidence_json"])
    assert str(branch["current_trial_plan_hash"]) == plan_hash
    assert evidence == {
        "trial_plan": canonical_trial_plan(plan),
        "trial_plan_hash": plan_hash,
    }
