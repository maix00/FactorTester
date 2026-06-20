"""Registry and lifecycle helpers for derived market-data artifacts."""

from .coordinator import ArtifactCoordinator, ensure_artifact_schema, start_background_ensure
from .model import ArtifactCoverage, DerivedArtifactSpec
from .registry import artifact_registry, register_artifact
from .storage import artifact_path, artifact_root, source_data_root

__all__ = [
    "ArtifactCoordinator",
    "ArtifactCoverage",
    "DerivedArtifactSpec",
    "artifact_registry",
    "ensure_artifact_schema",
    "register_artifact",
    "start_background_ensure",
    "artifact_path",
    "artifact_root",
    "source_data_root",
]
