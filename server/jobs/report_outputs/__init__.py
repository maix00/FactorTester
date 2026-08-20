"""Public output contract used by workers, HTTP routes, and the CLI."""

from .builders import build_report_artifacts
from .bundles import ReportBundle, bundle_reports
from .definitions import (
    OUTPUT_DEFINITIONS,
    artifact_description,
    default_output_requests,
    output_declarations,
    normalize_output_requests,
    output_capabilities,
    output_requests_for_analysis,
    output_requests_for_artifacts,
    result_retention_mode_for,
    source_artifacts_for,
    validate_output_requests,
)
from .models import GeneratedReport

__all__ = [
    "GeneratedReport", "ReportBundle", "bundle_reports", "OUTPUT_DEFINITIONS",
    "artifact_description",
    "default_output_requests",
    "build_report_artifacts", "normalize_output_requests",
    "output_capabilities", "output_declarations", "source_artifacts_for",
    "output_requests_for_analysis",
    "output_requests_for_artifacts",
    "result_retention_mode_for",
    "validate_output_requests",
]
