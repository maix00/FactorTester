"""Derived retention pin for TrialPlan-bearing graph traces."""

from __future__ import annotations

import sqlite3
from typing import Any

import orjson

from .contract import trial_plan_hash


def trial_plan_trace_retention(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
) -> dict[str, Any]:
    """Inspect low-frequency dependencies; never used by routine submission."""
    trace = conn.execute(
        """
        SELECT evidence_json FROM research_graph_trace
        WHERE trace_id=?
        """,
        (trace_id,),
    ).fetchone()
    if trace is None:
        raise KeyError("graph trace not found")
    evidence = orjson.loads(trace["evidence_json"]) or {}
    plan = evidence.get("trial_plan")
    if not isinstance(plan, dict):
        return {
            "trace_id": trace_id,
            "trial_plan_hash": "",
            "pinned": False,
            "branch_references": 0,
            "run_references": 0,
            "job_references": 0,
        }
    plan_hash = trial_plan_hash(plan)
    dependencies = conn.execute(
        """
        SELECT
          (
            SELECT COUNT(*) FROM research_graph_branches
            WHERE current_trial_plan_hash=?
          ) AS branch_references,
          (
            SELECT COUNT(*) FROM research_runs
            WHERE trial_plan_hash=?
          ) AS run_references,
          (
            SELECT COUNT(*)
            FROM research_jobs AS jobs
            JOIN research_runs AS runs ON runs.run_id=jobs.run_id
            WHERE runs.trial_plan_hash=?
          ) AS job_references
        """,
        (plan_hash, plan_hash, plan_hash),
    ).fetchone()
    branch_references = int(dependencies["branch_references"])
    run_references = int(dependencies["run_references"])
    job_references = int(dependencies["job_references"])
    return {
        "trace_id": trace_id,
        "trial_plan_hash": plan_hash,
        "pinned": any((
            branch_references,
            run_references,
            job_references,
        )),
        "branch_references": branch_references,
        "run_references": run_references,
        "job_references": job_references,
    }
