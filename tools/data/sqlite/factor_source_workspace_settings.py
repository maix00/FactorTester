"""SQLite-backed settings for factor workspace git configuration."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import Settings
from tools.data.sqlite.db import connect_sqlite

TABLE_NAME = "factor_source_workspace_settings"
FIXED_UPLOAD_BRANCH = "upload"
FIXED_DOWNLOAD_BRANCH = "download"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            username TEXT PRIMARY KEY,
            git_enabled INTEGER NOT NULL DEFAULT 0,
            git_repo_root TEXT NOT NULL DEFAULT '',
            auto_sync_branch TEXT NOT NULL DEFAULT '',
            force_sync_branch TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL
        )
        """
    )


def ensure_factor_source_workspace_settings_sqlite_store() -> str:
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
    return str(Settings.CACHE_DB_PATH)


def load_factor_source_workspace_settings(username: str) -> dict[str, Any] | None:
    if not username:
        return None
    try:
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            _ensure_schema(conn)
            row = conn.execute(
                f"""
                SELECT username, git_enabled, git_repo_root, auto_sync_branch, force_sync_branch, updated_at
                FROM {TABLE_NAME}
                WHERE username = ?
                """,
                (username,),
            ).fetchone()
            if row is None:
                return None
            return {
                "username": row["username"],
                "git_enabled": bool(row["git_enabled"]),
                "git_repo_root": str(row["git_repo_root"] or ""),
                "auto_sync_branch": str(row["auto_sync_branch"] or "") or FIXED_UPLOAD_BRANCH,
                "force_sync_branch": str(row["force_sync_branch"] or "") or FIXED_DOWNLOAD_BRANCH,
                "updated_at": float(row["updated_at"] or 0.0),
            }
    except Exception:
        return None


def save_factor_source_workspace_settings(
    username: str,
    *,
    git_enabled: bool,
    git_repo_root: str | None,
) -> str:
    if not username:
        return str(Settings.CACHE_DB_PATH)
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        _ensure_schema(conn)
        conn.execute(
            f"""
            INSERT INTO {TABLE_NAME} (
                username, git_enabled, git_repo_root, auto_sync_branch, force_sync_branch, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                git_enabled = excluded.git_enabled,
                git_repo_root = excluded.git_repo_root,
                auto_sync_branch = excluded.auto_sync_branch,
                force_sync_branch = excluded.force_sync_branch,
                updated_at = excluded.updated_at
            """,
            (
                username,
                1 if git_enabled else 0,
                str(git_repo_root or "").strip(),
                FIXED_UPLOAD_BRANCH,
                FIXED_DOWNLOAD_BRANCH,
                time.time(),
            ),
        )
    return str(Settings.CACHE_DB_PATH)
