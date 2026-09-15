"""Manager-side access to the shared report export policy.

The policy lives in the reporting layer (``tools.cli...report_export``) because
the native client export must produce exactly the same document as the
manager.  This module keeps the manager's routes importing a service name.
"""

from __future__ import annotations

from tools.cli.release.research_reporting.report_export import (
    MARKDOWN_CONTENT_TYPE,
    document_identity,
    download_name,
    export_timestamp,
    front_matter,
    markdown_export,
    principal_alias,
)

__all__ = [
    "MARKDOWN_CONTENT_TYPE",
    "document_identity",
    "download_name",
    "export_timestamp",
    "front_matter",
    "markdown_export",
    "principal_alias",
]
