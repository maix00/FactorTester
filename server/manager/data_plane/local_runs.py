"""Resolve explicitly uploaded client-local artifacts from private staging."""

from __future__ import annotations

import json
from pathlib import Path
import re

from tools.data.sqlite.db import connect_sqlite


class LocalRunArtifactOriginAdapter:
    """Resolve a local-run artifact only after its upload was acknowledged."""

    def __init__(self, *, database: str | Path, submission_root: str | Path) -> None:
        self.database = Path(database).expanduser().resolve()
        self.submission_root = Path(submission_root).expanduser().resolve()

    def __call__(self, transfer) -> Path:
        principal = str(getattr(transfer, "principal", "") or "").strip()
        object_id = str(getattr(transfer, "object_id", "") or "").strip()
        try:
            job_id, name = object_id.split(":", 1)
        except ValueError as exc:
            raise FileNotFoundError("local artifact reference is invalid") from exc
        with connect_sqlite(self.database, readonly=True, timeout=5.0) as db:
            row = db.execute(
                "SELECT payload_json FROM local_runs WHERE principal=? AND local_job_id=?",
                (principal, job_id),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("local run is unavailable")
        try:
            payload = json.loads(row[0] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FileNotFoundError("local run projection is invalid") from exc
        item = next(
            (value for value in payload.get("artifact_manifest") or ()
             if isinstance(value, dict) and str(value.get("name") or "") == name),
            None,
        )
        if not isinstance(item, dict) or item.get("upload_state") != "uploaded":
            raise FileNotFoundError("local artifact was not explicitly uploaded")
        upload_transfer_id = str(item.get("storage_transfer_id") or "").strip()
        if not upload_transfer_id:
            raise FileNotFoundError("local artifact upload is not committed")
        path = (
            self.submission_root
            / _safe_component(principal)
            / _safe_component(upload_transfer_id)
            / _safe_component(name)
        ).resolve()
        if self.submission_root not in path.parents or not path.is_file():
            raise FileNotFoundError("local artifact file is unavailable")
        return path


def _safe_component(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip(".-")
    if not result:
        raise FileNotFoundError("local artifact path is invalid")
    return result[:128]


__all__ = ["LocalRunArtifactOriginAdapter"]
