"""Public contracts for source-provided derived artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class ArtifactCoverage:
    product_name: str
    variant: str = "default"
    start_value: str | None = None
    end_value: str | None = None
    row_count: int | None = None
    entity_count: int | None = None


@dataclass(frozen=True)
class DerivedArtifactSpec:
    """One atomically published artifact supplied by a market-data source."""

    provider: str
    name: str
    variant: str
    output_path: Path
    build: Callable[[Path], None]
    coverage: Callable[[Path], Iterable[ArtifactCoverage]]
    source_paths: tuple[Path, ...] = field(default_factory=tuple)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    auto_build: bool = True
    schema_version: str = "1"
    accept_unmanaged_existing: bool = True
    on_published: Callable[[Path], None] | None = None

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.name}:{self.variant}"
