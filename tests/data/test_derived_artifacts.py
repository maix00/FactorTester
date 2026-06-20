from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.data.artifacts.coordinator import (
    ARTIFACT_COVERAGE_TABLE,
    ArtifactCoordinator,
)
from tools.data.artifacts.model import ArtifactCoverage, DerivedArtifactSpec
from tools.data.artifacts.registry import ArtifactRegistry
from tools.data.artifacts.storage import artifact_root, source_data_root


def _spec(
    root: Path,
    name: str,
    events: list[str],
    *,
    dependencies: tuple[str, ...] = (),
    variant: str = "default",
) -> DerivedArtifactSpec:
    output = root / f"{name}-{variant}.txt"

    def build(staging: Path) -> None:
        events.append(f"build:{name}:{variant}")
        staging.write_text(f"{name}:{variant}", encoding="utf-8")

    def coverage(path: Path):
        events.append(f"coverage:{name}:{variant}")
        yield ArtifactCoverage("TEST", variant=variant, row_count=1, entity_count=1)

    return DerivedArtifactSpec(
        provider="FakeSource",
        name=name,
        variant=variant,
        output_path=output,
        build=build,
        coverage=coverage,
        dependencies=dependencies,
    )


def test_artifact_variants_have_distinct_keys_and_dependency_order(tmp_path: Path):
    registry = ArtifactRegistry()
    events: list[str] = []
    primary = registry.register(_spec(tmp_path, "continuous", events, variant="primary"))
    secondary = registry.register(_spec(tmp_path, "continuous", events, variant="secondary"))
    curve = registry.register(
        _spec(tmp_path, "curve", events, variant="listed", dependencies=(primary.key, secondary.key))
    )
    coordinator = ArtifactCoordinator(registry=registry, db_path=tmp_path / "state.sqlite")

    result = coordinator.ensure(curve.key)

    assert result["status"] == "ready"
    assert events == [
        "build:continuous:primary",
        "coverage:continuous:primary",
        "build:continuous:secondary",
        "coverage:continuous:secondary",
        "build:curve:listed",
        "coverage:curve:listed",
    ]


def test_existing_artifact_is_indexed_without_rebuilding(tmp_path: Path):
    registry = ArtifactRegistry()
    events: list[str] = []
    spec = registry.register(_spec(tmp_path, "curve", events, variant="listed"))
    spec.output_path.write_text("existing", encoding="utf-8")
    coordinator = ArtifactCoordinator(registry=registry, db_path=tmp_path / "state.sqlite")

    result = coordinator.ensure(spec.key)

    assert result["status"] == "ready"
    assert events == ["coverage:curve:listed"]
    assert spec.output_path.read_text(encoding="utf-8") == "existing"
    with sqlite3.connect(tmp_path / "state.sqlite") as conn:
        row = conn.execute(
            f'SELECT product_name, variant FROM "{ARTIFACT_COVERAGE_TABLE}"'
        ).fetchone()
    assert row == ("TEST", "listed")


def test_busy_cross_platform_lock_does_not_start_second_builder(tmp_path: Path):
    registry = ArtifactRegistry()
    events: list[str] = []
    spec = registry.register(_spec(tmp_path, "curve", events))
    spec.output_path.with_name(spec.output_path.name + ".lock").write_text("pid=other\n", encoding="ascii")
    coordinator = ArtifactCoordinator(registry=registry, db_path=tmp_path / "state.sqlite")

    result = coordinator.ensure(spec.key)

    assert result["status"] == "building_elsewhere"
    assert events == []


def test_failed_force_rebuild_preserves_published_artifact(tmp_path: Path):
    registry = ArtifactRegistry()
    output = tmp_path / "curve.parquet"
    output.write_text("published", encoding="utf-8")

    def fail(staging: Path) -> None:
        staging.write_text("partial", encoding="utf-8")
        raise RuntimeError("boom")

    spec = registry.register(DerivedArtifactSpec(
        provider="FakeSource",
        name="curve",
        variant="listed",
        output_path=output,
        build=fail,
        coverage=lambda path: (),
    ))
    coordinator = ArtifactCoordinator(registry=registry, db_path=tmp_path / "state.sqlite")

    with pytest.raises(RuntimeError, match="boom"):
        coordinator.ensure(spec.key, force=True)

    assert output.read_text(encoding="utf-8") == "published"
    assert not list(tmp_path.glob(".*.tmp.parquet"))


def test_provider_storage_is_isolated_and_overridable(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("tools.data.artifacts.storage.DATA_DIR", str(tmp_path))

    assert artifact_root("LocalCNFutures") == tmp_path / "derived_artifacts" / "LocalCNFutures"
    assert artifact_root("LocalOptions") == tmp_path / "derived_artifacts" / "LocalOptions"
    assert source_data_root("LocalOptions") == tmp_path / "sources" / "LocalOptions"

    custom = tmp_path / "windows-mounted-source"
    monkeypatch.setenv("GTHT_SOURCE_DATA_DIR_LOCALOPTIONS", str(custom))
    assert source_data_root("LocalOptions") == custom


def test_local_source_registers_continuous_and_listed_curve_artifacts():
    from sources.LocalCNFutures.artifacts import CONTINUOUS_KEY, TERM_STRUCTURE_KEY
    from tools.data.artifacts.registry import artifact_registry

    assert artifact_registry.get(CONTINUOUS_KEY).variant == "primary_secondary"
    assert artifact_registry.get(TERM_STRUCTURE_KEY).variant == "listed_contracts"
    assert artifact_registry.get(TERM_STRUCTURE_KEY).dependencies == (CONTINUOUS_KEY,)
