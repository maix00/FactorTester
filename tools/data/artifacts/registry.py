"""Process-local registry populated by data-source adapter modules."""

from __future__ import annotations

from .model import DerivedArtifactSpec


class ArtifactRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, DerivedArtifactSpec] = {}

    def register(self, spec: DerivedArtifactSpec) -> DerivedArtifactSpec:
        # Source modules are hot-reloaded in development; the stable key owns
        # the slot and the reloaded adapter replaces its previous callables.
        self._specs[spec.key] = spec
        return spec

    def get(self, key: str) -> DerivedArtifactSpec:
        try:
            return self._specs[key]
        except KeyError as exc:
            raise KeyError(f"Unknown derived artifact: {key}") from exc

    def all(self) -> tuple[DerivedArtifactSpec, ...]:
        return tuple(self._specs[key] for key in sorted(self._specs))

    def clear(self) -> None:
        self._specs.clear()


artifact_registry = ArtifactRegistry()


def register_artifact(spec: DerivedArtifactSpec) -> DerivedArtifactSpec:
    return artifact_registry.register(spec)
