"""Shared deterministic fixtures for TrialPlan acceptance tests."""

from __future__ import annotations

import hashlib
from copy import deepcopy

import orjson

from server.jobs.models import JobRecord
from server.jobs.states import JobStatus
from server.services.research_run_identity import RUN_SPEC_VERSION
from server.services.trial_plan.contract import trial_plan_hash


def run_spec() -> dict:
    return {
        "run_spec_version": RUN_SPEC_VERSION,
        "workspace_id": "workspace-1",
        "analyses": ["ic"],
        "configuration": {
            "analyses": {
                "ic": {
                    "settings": {
                        "start_date": "2020-01-01",
                        "end_date": "2023-12-31",
                    },
                    "paths": ["CNFutures/黑色"],
                },
            },
        },
    }


def run_spec_with_dates(
    start_date: str,
    end_date: str,
    *,
    sample: str | None = None,
    **updates,
) -> dict:
    value = deepcopy(run_spec())
    settings = value["configuration"]["analyses"]["ic"]["settings"]
    settings["start_date"] = start_date
    settings["end_date"] = end_date
    if sample is not None:
        value["sample"] = sample
    value.update(updates)
    return value


def semantic_hash(value: dict) -> str:
    return hashlib.sha256(
        orjson.dumps(value, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def trial_plan(run_spec_hash: str) -> dict:
    return {
        "schema_version": 1,
        "trial_plan_id": "plan-1",
        "version": 1,
        "hypothesis_ref": "hypothesis-1",
        "trial_family": "family-1",
        "protocol_ref": "cross-sectional-ic@1",
        "outcomes": {
            "primary": ["rank-ic"],
            "secondary": ["coverage"],
        },
        "sample_roles": [{
            "sample_ref": "selection-2020-2023",
            "sample_hash": "d" * 64,
            "role": "selection",
            "run_spec_hashes": [run_spec_hash],
        }],
        "comparisons": [{
            "comparison_id": "main-comparison",
            "members": [{
                "run_spec_hash": run_spec_hash,
                "trial_role": "selection",
            }],
        }],
        "stopping": {
            "rule_ref": "fixed-sample@1",
            "monitored_outcomes": ["rank-ic"],
            "parameters": {"minimum_observations": 250},
        },
        "multiplicity": {
            "method_ref": "none@1",
            "family_ref": "family-1",
            "dependence_assumptions": [],
        },
        "criteria": {
            "rejection_ref": "ic-reject@1",
            "revision_ref": "ic-revise@1",
            "continuation_ref": "ic-continue@1",
        },
    }


def trial_plan_v4() -> dict:
    value = trial_plan("a" * 64)
    value.update({
        "schema_version": 4,
        "decision_contract_hash": "1" * 64,
        "methodology_hash": "2" * 64,
        "parent_trial_plan_hash": None,
        "stage_policy": {
            "ordered_stages": [
                "selection",
                "validation",
                "confirmation",
            ],
            "entry_stage": "selection",
            "entry_basis_ref": "decision-contract:new-research",
        },
        "sample_roles": [
            {
                "sample_ref": "selection-2020-2022",
                "sample_hash": "d" * 64,
                "role": "selection",
                "run_spec_hashes": ["a" * 64],
            },
            {
                "sample_ref": "validation-2023",
                "sample_hash": "e" * 64,
                "role": "validation",
                "run_spec_hashes": ["b" * 64],
            },
            {
                "sample_ref": "confirmation-2024",
                "sample_hash": "f" * 64,
                "role": "confirmation",
                "run_spec_hashes": ["c" * 64],
            },
        ],
        "comparisons": [{
            "comparison_id": "main-comparison",
            "members": [
                {
                    "run_spec_hash": "a" * 64,
                    "trial_role": "candidate",
                },
                {
                    "run_spec_hash": "b" * 64,
                    "trial_role": "candidate",
                },
                {
                    "run_spec_hash": "c" * 64,
                    "trial_role": "candidate",
                },
            ],
        }],
    })
    return value


def trial_binding(plan: dict) -> dict:
    return {
        "trial_plan": plan,
        "trial_plan_hash": trial_plan_hash(plan),
        "trial_plan_version": 1,
        "trial_role": "selection",
        "comparison_id": "main-comparison",
    }


def job_record(
    run_id: str,
    run_spec_value: dict,
    job_id: str = "job-1",
) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        run_id=run_id,
        owner="alice",
        workspace_id="workspace-1",
        kind="ic",
        status=JobStatus.SUBMITTED,
        job_spec={"run_spec": run_spec_value},
        run_spec_hash=semantic_hash(run_spec_value),
    )
