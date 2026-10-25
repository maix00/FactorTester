"""CouchDB-backed report documents and content-addressed attachments."""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.request
from dataclasses import dataclass, field
from typing import Any


def content_name(data: bytes, suffix: str) -> str:
    return f"{hashlib.sha256(data).hexdigest()}.{suffix.lstrip('.')}"


@dataclass
class ReportDocument:
    report_ref: str
    job_id: str
    owner: str
    schema_version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
    attachments: dict[str, str] = field(default_factory=dict)

    def to_doc(self) -> dict[str, Any]:
        return {
            "_id": self.report_ref,
            "schema_version": self.schema_version,
            "kind": "report",
            "job_id": self.job_id,
            "owner": self.owner,
            "metadata": dict(self.metadata),
            "attachments": dict(self.attachments),
            "content_sha256": hashlib.sha256(
                json.dumps(self.metadata, sort_keys=True).encode()
            ).hexdigest(),
        }


class CouchDBObjectStore:
    def __init__(self, base_url: str, database: str, *, username="", password="",
                 timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.database = database.strip("/")
        self.username = username
        self.password = password
        self.timeout = timeout

    def _request(self, method: str, path: str, body: bytes | None = None,
                 content_type: str = "application/json") -> tuple[int, bytes]:
        request = urllib.request.Request(
            f"{self.base_url}/{self.database}/{path.lstrip('/')}",
            data=body, method=method,
            headers={"Content-Type": content_type, "Accept": "application/json"},
        )
        if self.username:
            token = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            request.add_header("Authorization", f"Basic {token}")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.status, response.read()

    def put_report(self, report: ReportDocument, *, overwrite: bool = False) -> None:
        doc = report.to_doc()
        if overwrite:
            try:
                _, raw = self._request("GET", report.report_ref)
                current = json.loads(raw)
                doc["_rev"] = current["_rev"]
                if "_attachments" in current:
                    doc["_attachments"] = current["_attachments"]
            except Exception:
                pass
        self._request("PUT", report.report_ref, json.dumps(doc).encode())

    def put_attachment(self, report_ref: str, name: str, data: bytes,
                       content_type: str) -> None:
        _, raw = self._request("GET", report_ref)
        current = json.loads(raw)
        self._request(
            "PUT", f"{report_ref}/{name}?rev={current['_rev']}", data,
            content_type=content_type,
        )

    def conflicts(self, report_ref: str) -> list[str]:
        _, raw = self._request("GET", f"{report_ref}?conflicts=true")
        return list(json.loads(raw).get("_conflicts") or [])

    def get_attachment(self, report_ref: str, name: str) -> bytes:
        return self._request("GET", f"{report_ref}/{name}")[1]

    def start_replication(self, target_url: str, *, continuous: bool = True,
                          filter: str = "") -> dict[str, Any]:
        body = self.replication_config(
            target_url, continuous=continuous, filter=filter,
        )
        request = urllib.request.Request(
            f"{self.base_url}/_replicate", data=json.dumps(body).encode(),
            method="POST", headers={"Content-Type": "application/json"},
        )
        if self.username:
            token = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            request.add_header("Authorization", f"Basic {token}")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    def replication_config(self, target_url: str, *, continuous: bool = True,
                           filter: str = "") -> dict[str, Any]:
        source = f"{self.base_url}/{self.database}"
        return {
            "source": source, "target": target_url.rstrip("/"),
            "continuous": bool(continuous),
            **({"filter": filter} if filter else {}),
        }


def write_report(store: CouchDBObjectStore, *, job_id: str, owner: str,
                 revision: int, metadata: dict[str, Any],
                 files: dict[str, tuple[bytes, str]]) -> ReportDocument:
    report = ReportDocument(
        report_ref=f"report:{job_id}:{int(revision)}", job_id=job_id,
        owner=owner, metadata=dict(metadata),
    )
    store.put_report(report)
    for name, (data, content_type) in files.items():
        stored = content_name(data, name.rsplit(".", 1)[-1] if "." in name else "bin")
        report.attachments[name] = stored
        store.put_attachment(report.report_ref, stored, data, content_type)
    store.put_report(report, overwrite=True)
    return report


def publish_job_report(*, job_id: str, attempt: int, owner: str,
                       reports_dir: str, metadata: dict[str, Any] | None = None,
                       store: CouchDBObjectStore | None = None) -> str | None:
    """Publish a completed Job report directory; None when CouchDB is not configured."""
    import os
    from pathlib import Path

    if store is None:
        url = os.environ.get("FACTORTESTER_COUCHDB_URL", "").strip()
        if not url:
            return None
        store = CouchDBObjectStore(
            url, os.environ.get("FACTORTESTER_COUCHDB_DB", "ft_objects").strip(),
            username=os.environ.get("FACTORTESTER_COUCHDB_USER", ""),
            password=os.environ.get("FACTORTESTER_COUCHDB_PASSWORD", ""),
        )
    root = Path(reports_dir)
    files = {}
    for path in sorted(root.iterdir()):
        if path.is_file() and path.name != "nautilus_receipt.json":
            files[path.name] = (path.read_bytes(), "text/html" if path.suffix == ".html" else "text/csv")
    if not files:
        return None
    report = write_report(
        store, job_id=job_id, owner=owner, revision=max(1, int(attempt)),
        metadata={"kind": "nautilus_report", **(metadata or {})}, files=files,
    )
    return report.report_ref
