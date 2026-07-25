"""Public output contract used by workers, HTTP routes, and the CLI."""

from .builders import build_report_artifacts
from .definitions import (
    OUTPUT_DEFINITIONS,
    artifact_description,
    output_declarations,
    normalize_output_requests,
    output_capabilities,
    source_artifacts_for,
)
from .models import GeneratedReport

__all__ = [
    "GeneratedReport", "OUTPUT_DEFINITIONS", "artifact_description",
    "build_report_artifacts", "normalize_output_requests",
    "output_capabilities", "output_declarations", "source_artifacts_for",
]
