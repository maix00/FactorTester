"""Read-only compatibility access for historical TrialPlan records."""

from __future__ import annotations

from typing import Any

import orjson
import settings as Settings

from tools.data.sqlite.db import connect_sqlite


def load(*, owner: str, trial_plan_hash: str) -> dict[str, Any] | None:
    _ensure_schema()
    digest = str(trial_plan_hash).removeprefix("sha256:")
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT trial_plan_hash, trial_plan_id, trial_plan_version,
                   trial_plan_json, created_at
            FROM direct_trial_plans
            WHERE owner=? AND trial_plan_hash=?
            """,
            (owner, digest),
        ).fetchone()
    if row is None:
        return None
    return {
        "binding_origin": "agent_direct",
        "trial_plan_ref": "trial-plan:sha256:" + str(row["trial_plan_hash"]),
        "trial_plan_hash": str(row["trial_plan_hash"]),
        "trial_plan_id": str(row["trial_plan_id"]),
        "trial_plan_version": int(row["trial_plan_version"]),
        "trial_plan": orjson.loads(row["trial_plan_json"]),
        "created_at": float(row["created_at"]),
    }


def _ensure_schema() -> None:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS direct_trial_plans (
                owner TEXT NOT NULL,
                trial_plan_hash TEXT NOT NULL,
                trial_plan_id TEXT NOT NULL,
                trial_plan_version INTEGER NOT NULL,
                trial_plan_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (owner, trial_plan_hash)
            )
            """
        )
