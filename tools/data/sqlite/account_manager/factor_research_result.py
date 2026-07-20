"""SQLite storage for structured factor research results."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

import settings as Settings
from tools.data.sqlite.db import connect_sqlite


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normal_date(value: str | None) -> str:
    return str(value or "").strip()


def _metric_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _make_run_id(payload: dict[str, Any]) -> str:
    material = _json_dumps(
        {
            "username": payload.get("username") or "",
            "ff_alias": payload.get("ff_alias") or "",
            "factor_alias": payload.get("factor_alias") or "",
            "product_group": payload.get("product_group") or "",
            "start_date": payload.get("start_date") or "",
            "end_date": payload.get("end_date") or "",
            "test_type": payload.get("test_type") or "",
            "sample_role": payload.get("sample_role") or "",
            "regime_label": payload.get("regime_label") or "",
            "slice_name": payload.get("slice_name") or "",
            "config_hash": payload.get("config_hash") or "",
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def config_hash(config: dict[str, Any] | None) -> str:
    """Return a stable short hash for a research run configuration."""
    if not config:
        return ""
    return hashlib.sha256(_json_dumps(config).encode("utf-8")).hexdigest()[:24]


def ensure_factor_research_result_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_factor_research_runs (
            run_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            ff_alias TEXT NOT NULL,
            factor_alias TEXT NOT NULL,
            factor_source TEXT NOT NULL DEFAULT '',
            product_group TEXT NOT NULL DEFAULT '',
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            test_type TEXT NOT NULL,
            sample_role TEXT NOT NULL DEFAULT '',
            regime_label TEXT NOT NULL DEFAULT '',
            slice_name TEXT NOT NULL DEFAULT '',
            config_hash TEXT NOT NULL DEFAULT '',
            config_json TEXT NOT NULL DEFAULT '{}',
            report_path TEXT NOT NULL DEFAULT '',
            artifact_path TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    existing_columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(account_factor_research_runs)").fetchall()
    }
    for column in ("sample_role", "regime_label", "slice_name"):
        if column not in existing_columns:
            conn.execute(
                f"ALTER TABLE account_factor_research_runs ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
            )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_factor_research_metrics (
            run_id TEXT NOT NULL,
            metric_key TEXT NOT NULL,
            metric_value REAL,
            metric_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (run_id, metric_key),
            FOREIGN KEY (run_id)
                REFERENCES account_factor_research_runs(run_id)
                ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_factor_research_runs_lookup
        ON account_factor_research_runs (
            username, ff_alias, product_group, test_type, start_date, end_date
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_factor_research_metrics_lookup
        ON account_factor_research_metrics (metric_key, metric_value)
        """
    )


def save_factor_research_run(
    username: str,
    *,
    ff_alias: str,
    factor_alias: str,
    start_date: str,
    end_date: str,
    test_type: str,
    metrics: dict[str, Any],
    product_group: str = "",
    factor_source: str = "",
    config: dict[str, Any] | None = None,
    config_hash_value: str | None = None,
    report_path: str = "",
    artifact_path: str = "",
    note: str = "",
    sample_role: str = "",
    regime_label: str = "",
    slice_name: str = "",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Upsert one structured factor research run and its metrics."""
    cfg = dict(config or {})
    meta = cfg.get("research_meta") if isinstance(cfg.get("research_meta"), dict) else {}
    cfg_hash = str(config_hash_value or config_hash(cfg))
    payload = {
        "username": str(username or ""),
        "ff_alias": str(ff_alias or ""),
        "factor_alias": str(factor_alias or ""),
        "factor_source": str(factor_source or ""),
        "product_group": str(product_group or ""),
        "start_date": _normal_date(start_date),
        "end_date": _normal_date(end_date),
        "test_type": str(test_type or ""),
        "sample_role": str(sample_role or meta.get("sample_role") or ""),
        "regime_label": str(regime_label or meta.get("regime_label") or ""),
        "slice_name": str(slice_name or meta.get("slice_name") or ""),
        "config_hash": cfg_hash,
        "config_json": _json_dumps(cfg),
        "report_path": str(report_path or ""),
        "artifact_path": str(artifact_path or ""),
        "note": str(note or ""),
    }
    if not payload["username"]:
        raise ValueError("username is required")
    for key in ("ff_alias", "factor_alias", "start_date", "end_date", "test_type"):
        if not payload[key]:
            raise ValueError(f"{key} is required")
    payload["run_id"] = str(run_id or _make_run_id(payload))
    now = time.time()
    with connect_sqlite(Settings.CACHE_DB_PATH, foreign_keys=True) as conn:
        ensure_factor_research_result_schema(conn)
        existing = conn.execute(
            "SELECT created_at FROM account_factor_research_runs WHERE run_id = ?",
            (payload["run_id"],),
        ).fetchone()
        created_at = float(existing["created_at"]) if existing is not None else now
        conn.execute(
            """
            INSERT INTO account_factor_research_runs (
                run_id, username, ff_alias, factor_alias, factor_source, product_group,
                start_date, end_date, test_type, sample_role, regime_label, slice_name, config_hash, config_json,
                report_path, artifact_path, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                username = excluded.username,
                ff_alias = excluded.ff_alias,
                factor_alias = excluded.factor_alias,
                factor_source = excluded.factor_source,
                product_group = excluded.product_group,
                start_date = excluded.start_date,
                end_date = excluded.end_date,
                test_type = excluded.test_type,
                sample_role = excluded.sample_role,
                regime_label = excluded.regime_label,
                slice_name = excluded.slice_name,
                config_hash = excluded.config_hash,
                config_json = excluded.config_json,
                report_path = excluded.report_path,
                artifact_path = excluded.artifact_path,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (
                payload["run_id"],
                payload["username"],
                payload["ff_alias"],
                payload["factor_alias"],
                payload["factor_source"],
                payload["product_group"],
                payload["start_date"],
                payload["end_date"],
                payload["test_type"],
                payload["sample_role"],
                payload["regime_label"],
                payload["slice_name"],
                payload["config_hash"],
                payload["config_json"],
                payload["report_path"],
                payload["artifact_path"],
                payload["note"],
                created_at,
                now,
            ),
        )
        conn.execute(
            "DELETE FROM account_factor_research_metrics WHERE run_id = ?",
            (payload["run_id"],),
        )
        for metric_key, metric_value in sorted((metrics or {}).items()):
            conn.execute(
                """
                INSERT INTO account_factor_research_metrics (
                    run_id, metric_key, metric_value, metric_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload["run_id"],
                    str(metric_key),
                    _metric_number(metric_value),
                    _json_dumps(metric_value),
                    now,
                ),
            )
    saved = dict(payload)
    saved["metrics"] = dict(metrics or {})
    return saved


def _rows_to_runs(rows: list[sqlite3.Row], metrics_by_run: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        config: dict[str, Any]
        try:
            loaded = json.loads(row["config_json"])
            config = loaded if isinstance(loaded, dict) else {}
        except Exception:
            config = {}
        result.append(
            {
                "run_id": row["run_id"],
                "username": row["username"],
                "ff_alias": row["ff_alias"],
                "factor_alias": row["factor_alias"],
                "factor_source": row["factor_source"],
                "product_group": row["product_group"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "test_type": row["test_type"],
                "sample_role": row["sample_role"],
                "regime_label": row["regime_label"],
                "slice_name": row["slice_name"],
                "config_hash": row["config_hash"],
                "config": config,
                "report_path": row["report_path"],
                "artifact_path": row["artifact_path"],
                "artifact_exists": _path_exists(row["artifact_path"]),
                "report_exists": _path_exists(row["report_path"]),
                "note": row["note"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "metrics": metrics_by_run.get(row["run_id"], {}),
            }
        )
    return result


def _path_exists(path: str) -> bool | None:
    text = str(path or "")
    if not text:
        return None
    try:
        return Path(text).exists()
    except OSError:
        return False


def _load_metrics(conn: sqlite3.Connection, run_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    rows = conn.execute(
        f"""
        SELECT run_id, metric_key, metric_json
        FROM account_factor_research_metrics
        WHERE run_id IN ({placeholders})
        ORDER BY metric_key
        """,
        run_ids,
    ).fetchall()
    metrics_by_run: dict[str, dict[str, Any]] = {run_id: {} for run_id in run_ids}
    for row in rows:
        try:
            value = json.loads(row["metric_json"])
        except Exception:
            value = None
        metrics_by_run.setdefault(row["run_id"], {})[row["metric_key"]] = value
    return metrics_by_run


def list_factor_research_runs(
    username: str,
    *,
    ff_alias: str | None = None,
    factor_alias: str | None = None,
    product_group: str | None = None,
    test_type: str | None = None,
    sample_role: str | None = None,
    regime_label: str | None = None,
    slice_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    overlap: bool = True,
    min_metrics: dict[str, float] | None = None,
    max_metrics: dict[str, float] | None = None,
    order_by_metric: str | None = None,
    descending: bool = True,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List research runs visible within one user's own factor research index."""
    clauses = ["username = ?"]
    params: list[Any] = [str(username or "")]
    if ff_alias:
        clauses.append("ff_alias = ?")
        params.append(str(ff_alias))
    if factor_alias:
        clauses.append("factor_alias = ?")
        params.append(str(factor_alias))
    if product_group:
        clauses.append("product_group = ?")
        params.append(str(product_group))
    if test_type:
        clauses.append("test_type = ?")
        params.append(str(test_type))
    if sample_role:
        clauses.append("sample_role = ?")
        params.append(str(sample_role))
    if regime_label:
        clauses.append("regime_label = ?")
        params.append(str(regime_label))
    if slice_name:
        clauses.append("slice_name = ?")
        params.append(str(slice_name))
    start = _normal_date(start_date)
    end = _normal_date(end_date)
    if start and end:
        if overlap:
            clauses.append("end_date >= ? AND start_date <= ?")
            params.extend([start, end])
        else:
            clauses.append("start_date >= ? AND end_date <= ?")
            params.extend([start, end])
    elif start:
        clauses.append("end_date >= ?" if overlap else "start_date >= ?")
        params.append(start)
    elif end:
        clauses.append("start_date <= ?" if overlap else "end_date <= ?")
        params.append(end)

    sql = (
        "SELECT * FROM account_factor_research_runs "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY updated_at DESC"
    )
    with connect_sqlite(Settings.CACHE_DB_PATH, foreign_keys=True) as conn:
        ensure_factor_research_result_schema(conn)
        rows = conn.execute(sql, params).fetchall()
        run_ids = [str(row["run_id"]) for row in rows]
        metrics_by_run = _load_metrics(conn, run_ids)

    runs = _rows_to_runs(rows, metrics_by_run)

    def _passes(run: dict[str, Any]) -> bool:
        metrics = run.get("metrics") or {}
        for key, threshold in (min_metrics or {}).items():
            value = _metric_number(metrics.get(key))
            if value is None or value < float(threshold):
                return False
        for key, threshold in (max_metrics or {}).items():
            value = _metric_number(metrics.get(key))
            if value is None or value > float(threshold):
                return False
        return True

    runs = [run for run in runs if _passes(run)]
    if order_by_metric:
        missing_rank = float("-inf") if descending else float("inf")

        def _sort_value(run: dict[str, Any]) -> float:
            value = _metric_number((run.get("metrics") or {}).get(order_by_metric))
            return value if value is not None else missing_rank

        runs.sort(key=_sort_value, reverse=descending)
    if limit is not None and limit >= 0:
        runs = runs[:limit]
    return runs


def delete_factor_research_run(username: str, run_id: str) -> bool:
    with connect_sqlite(Settings.CACHE_DB_PATH, foreign_keys=True) as conn:
        ensure_factor_research_result_schema(conn)
        cursor = conn.execute(
            "DELETE FROM account_factor_research_runs WHERE username = ? AND run_id = ?",
            (str(username or ""), str(run_id or "")),
        )
    return bool(cursor.rowcount)
