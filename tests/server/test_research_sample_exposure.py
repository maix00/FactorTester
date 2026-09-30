"""Independent ResearchRun sample exposure checks."""

from __future__ import annotations

import json
import sqlite3

import pytest

from server.services.research_sample_exposure import (
    validate_protected_sample_exposure,
)


def _connection(tmp_path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "sample-exposure.sqlite")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE research_runs (
            owner TEXT NOT NULL,
            trial_plan_hash TEXT NOT NULL DEFAULT '',
            trial_stage TEXT NOT NULL DEFAULT '',
            trial_plan_schema_version INTEGER NOT NULL DEFAULT 0,
            sample_identity_hash TEXT NOT NULL DEFAULT '',
            sample_start TEXT NOT NULL DEFAULT '',
            sample_end TEXT NOT NULL DEFAULT '',
            sample_universe_hash TEXT NOT NULL DEFAULT '',
            run_spec_json TEXT NOT NULL DEFAULT '',
            sample_universe_members_json TEXT NOT NULL DEFAULT ''
        )
        """
    )
    return conn


def _insert_prior(
    conn: sqlite3.Connection,
    *,
    owner: str = "alice",
    plan_hash: str = "plan-selection",
    stage: str = "selection",
    start: str = "2024-01-01",
    end: str = "2024-12-31",
    members: list[str] | None = None,
    run_spec: dict | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO research_runs (
            owner, trial_plan_hash, trial_stage,
            trial_plan_schema_version, sample_identity_hash,
            sample_start, sample_end, run_spec_json,
            sample_universe_members_json
        ) VALUES (?, ?, ?, 2, 'prior-sample', ?, ?, ?, ?)
        """,
        (
            owner,
            plan_hash,
            stage,
            start,
            end,
            "" if run_spec is None else json.dumps(run_spec),
            "" if members is None else json.dumps(members),
        ),
    )


def _run_spec(members: list[str], *, start: str, end: str) -> dict:
    return {
        "run_spec_version": 3,
        "analyses": ["ic"],
        "configuration": {"analyses": {"ic": {
            "settings": {"start_date": start, "end_date": end},
            "paths": members,
        }}},
    }


def _validate(
    conn: sqlite3.Connection,
    current_members: list[str] | None = None,
) -> None:
    validate_protected_sample_exposure(
        conn,
        owner="alice",
        trial_plan_hash="plan-confirmation",
        trial_plan_schema_version=2,
        trial_stage="confirmation",
        sample_identity_hash="current-sample",
        sample_start="2024-01-01",
        sample_end="2024-12-31",
        sample_universe_members_json=json.dumps(
            current_members or ["a", "b"]
        ),
    )


@pytest.mark.parametrize(
    ("prior_members", "prior_start", "prior_end", "should_reject"),
    [
        (["a", "b"], "2024-01-01", "2024-12-31", True),  # identical
        (["a"], "2024-01-01", "2024-12-31", True),  # subset
        (["a", "b", "c"], "2024-01-01", "2024-12-31", True),  # superset
        (["b", "c"], "2024-01-01", "2024-12-31", True),  # partial overlap
        (["b"], "2024-06-01", "2024-08-31", True),  # date subset
        (["c", "d"], "2024-01-01", "2024-12-31", False),  # no products
        (["a", "b"], "2025-01-01", "2025-12-31", False),  # no dates
    ],
)
def test_protected_sample_overlap_uses_product_and_date_intersection(
    tmp_path,
    prior_members: list[str],
    prior_start: str,
    prior_end: str,
    should_reject: bool,
) -> None:
    conn = _connection(tmp_path)
    _insert_prior(
        conn,
        members=prior_members,
        start=prior_start,
        end=prior_end,
    )

    if should_reject:
        with pytest.raises(ValueError, match="already exposed"):
            _validate(conn)
    else:
        _validate(conn)
    conn.close()


def test_overlapping_runs_are_scoped_to_the_same_owner(tmp_path) -> None:
    conn = _connection(tmp_path)
    _insert_prior(conn, owner="bob", members=["a", "b"])

    _validate(conn)

    conn.close()


@pytest.mark.parametrize("raw_members", ["", "not-json", "{}", "[]", '["a", 1]'])
def test_unknown_prior_membership_fails_closed_for_overlapping_dates(
    tmp_path,
    raw_members: str,
) -> None:
    conn = _connection(tmp_path)
    conn.execute(
        """
        INSERT INTO research_runs (
            owner, trial_plan_hash, trial_stage,
            trial_plan_schema_version, sample_identity_hash,
            sample_start, sample_end, sample_universe_members_json
        ) VALUES ('alice', 'old-plan', 'selection', 1, '',
                  '2024-01-01', '2024-12-31', ?)
        """,
        (raw_members,),
    )

    with pytest.raises(ValueError, match="prior product membership cannot be proven"):
        _validate(conn)
    conn.close()


def test_unbound_prior_run_without_a_date_range_is_not_a_comparable_exposure(
    tmp_path,
) -> None:
    conn = _connection(tmp_path)
    _insert_prior(conn, members=None, start="", end="")

    _validate(conn)

    conn.close()


def test_missing_member_snapshot_recovers_from_immutable_runspec(
    tmp_path,
) -> None:
    conn = _connection(tmp_path)
    product = "Product/Futures/CNFutures/_products/AP.CZC"
    _insert_prior(
        conn,
        members=None,
        run_spec=_run_spec(
            [product], start="2024-01-01", end="2024-12-31",
        ),
    )

    with pytest.raises(ValueError, match="already exposed"):
        _validate(conn, current_members=[product, "other"])
    conn.close()


def test_non_protected_run_does_not_query_or_require_membership(tmp_path) -> None:
    conn = _connection(tmp_path)
    validate_protected_sample_exposure(
        conn,
        owner="alice",
        trial_plan_hash="plan-selection",
        trial_plan_schema_version=2,
        trial_stage="selection",
        sample_identity_hash="",
        sample_start="",
        sample_end="",
        sample_universe_members_json="",
    )
    conn.close()
