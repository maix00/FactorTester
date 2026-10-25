"""Single switch for CouchDB library/report authority during the cutover."""

from __future__ import annotations

import os


def authority_enabled() -> bool:
    return str(os.environ.get("TRADERESEARCH_COUCHDB_AUTHORITY", "")).lower() in {
        "1", "true", "yes",
    }


def libraries_read_enabled() -> bool:
    return authority_enabled() or str(
        os.environ.get("TRADERESEARCH_LIBRARIES_COUCHDB_READ", "")
    ).lower() in {"1", "true", "yes"}


def libraries_write_enabled() -> bool:
    return authority_enabled() or str(
        os.environ.get("TRADERESEARCH_LIBRARIES_COUCHDB_WRITE", "")
    ).lower() in {"1", "true", "yes"}


def research_reports_read_enabled() -> bool:
    return authority_enabled() or str(
        os.environ.get("TRADERESEARCH_RESEARCH_REPORTS_COUCHDB_READ", "")
    ).lower() in {"1", "true", "yes"}
