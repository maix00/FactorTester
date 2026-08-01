"""Validation for local-file Evidence provenance."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
from typing import Any
from urllib.parse import urlparse


_KINDS = {"authoritative_download", "git_blob"}
_METHODS = {"browser", "http", "api", "script"}


def validate_file_provenance(value: Any) -> dict[str, Any]:
    """Require a reproducible authority path for every local file source."""
    if not isinstance(value, dict):
        raise ValueError("file provenance must be an object")
    kind = str(value.get("provenance_kind") or "")
    if kind not in _KINDS:
        raise ValueError(
            "file provenance_kind must be authoritative_download or git_blob"
        )
    return (
        _authoritative_download(value)
        if kind == "authoritative_download"
        else _git_blob(value)
    )


def _authoritative_download(value: dict[str, Any]) -> dict[str, Any]:
    required = {
        "provenance_kind", "source_url", "publisher", "retrieved_at",
        "acquisition",
    }
    if set(value) != required:
        raise ValueError(
            "authoritative_download provenance requires provenance_kind, "
            "source_url, publisher, retrieved_at and acquisition"
        )
    url = _web_url(value["source_url"], "source_url")
    publisher = _text(value["publisher"], "publisher")
    retrieved_at = _timestamp(value["retrieved_at"])
    acquisition = value["acquisition"]
    if not isinstance(acquisition, dict):
        raise ValueError("file provenance acquisition must be an object")
    allowed = {"method", "script_ref", "request_parameters", "license_ref"}
    if set(acquisition) - allowed:
        raise ValueError("file provenance acquisition contains unknown fields")
    method = str(acquisition.get("method") or "")
    if method not in _METHODS:
        raise ValueError("file provenance acquisition.method is invalid")
    script_ref = str(acquisition.get("script_ref") or "")
    if method == "script" and not script_ref:
        raise ValueError("script acquisition requires a frozen script_ref")
    parameters = acquisition.get("request_parameters", {})
    if not isinstance(parameters, dict):
        raise ValueError("request_parameters must be an object")
    normalized_acquisition = {
        "method": method,
        "request_parameters": deepcopy(parameters),
    }
    if script_ref:
        normalized_acquisition["script_ref"] = _text(
            script_ref, "script_ref",
        )
    if acquisition.get("license_ref"):
        normalized_acquisition["license_ref"] = _text(
            acquisition["license_ref"], "license_ref",
        )
    return {
        "provenance_kind": "authoritative_download",
        "source_url": url,
        "publisher": publisher,
        "retrieved_at": retrieved_at,
        "acquisition": normalized_acquisition,
    }


def _git_blob(value: dict[str, Any]) -> dict[str, Any]:
    required = {
        "provenance_kind", "repository_url", "revision", "blob_hash",
        "relative_path",
    }
    if set(value) != required:
        raise ValueError(
            "git_blob provenance requires provenance_kind, repository_url, "
            "revision, blob_hash and relative_path"
        )
    revision = str(value["revision"])
    blob_hash = str(value["blob_hash"])
    if re.fullmatch(r"[0-9a-f]{40,64}", revision) is None:
        raise ValueError("file provenance revision is invalid")
    if re.fullmatch(r"[0-9a-f]{40,64}", blob_hash) is None:
        raise ValueError("file provenance blob_hash is invalid")
    relative_path = _text(value["relative_path"], "relative_path")
    if relative_path.startswith("/") or ".." in relative_path.split("/"):
        raise ValueError("file provenance relative_path is invalid")
    return {
        "provenance_kind": "git_blob",
        "repository_url": _web_url(value["repository_url"], "repository_url"),
        "revision": revision,
        "blob_hash": blob_hash,
        "relative_path": relative_path,
    }


def _web_url(value: Any, field: str) -> str:
    text = _text(value, field)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"file provenance {field} must use http or https")
    return text


def _timestamp(value: Any) -> str:
    text = _text(value, "retrieved_at")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("file provenance retrieved_at must be ISO-8601") from exc
    return text


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValueError(f"file provenance {field} is invalid")
    return value.strip()
