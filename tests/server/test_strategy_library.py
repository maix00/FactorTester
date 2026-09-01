from __future__ import annotations

from pathlib import Path

import pytest

from server.services import configuration_strategies
from server.services.strategy_bindings import compile_configuration_strategies
from server.services.strategy_library import StrategyLibraryService
from server.services.strategy_source_inspection import inspect_source


SOURCE = """from tools.testers.backtest.engines.native.strategy import Strategy

class Demo(Strategy):
    def on_bar(self, ctx, bar):
        return None
"""


SOURCE_V2 = SOURCE.replace("return None", "return {'changed': True}")


def library(tmp_path: Path) -> StrategyLibraryService:
    return StrategyLibraryService(tmp_path / "manager.sqlite", account_provider=lambda: [])


def create_strategy(
    service: StrategyLibraryService,
    *,
    owner: str = "alice",
    source: str = SOURCE,
    visibility: str = "private",
) -> dict:
    return service.create(
        {
            "name": "Demo strategy",
            "description": "A test actor",
            "visibility": visibility,
            "entrypoint": "Demo",
            "source_code": source,
        },
        principal=owner,
    )["strategy"]


def test_library_requires_a_native_strategy_entrypoint(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="native Strategy"):
        inspect_source("class NotAStrategy:\n    pass\n", "NotAStrategy")

    strategy = create_strategy(library(tmp_path))
    assert strategy["current_revision"]["entrypoint"] == "Demo"
    assert strategy["current_revision"]["hooks"][0]["name"] == "on_bar"


def test_source_inspection_includes_inherited_callbacks(tmp_path: Path) -> None:
    source = """from tools.testers.backtest.engines.native.strategy import Strategy

class Base(Strategy):
    def on_bar(self, ctx, bar):
        return None

class Child(Base):
    def on_order_filled(self, ctx, order):
        return None
"""
    inspection = inspect_source(source, "Child")
    assert inspection["callbacks"] == ["on_bar", "on_order_filled"]
    assert [hook["name"] for hook in inspection["hooks"]] == ["on_order_filled"]
    assert [hook["name"] for hook in inspection["effective_hooks"]] == [
        "on_order_filled", "on_bar",
    ]
    assert inspection["effective_hooks"][1]["declared_on"] == "Base"


def test_library_scopes_and_immutable_revisions(tmp_path: Path) -> None:
    service = StrategyLibraryService(
        tmp_path / "manager.sqlite",
        account_provider=lambda: [{"username": "bob", "parent_username": "alice"}],
    )
    strategy = create_strategy(service)
    create_strategy(service, owner="bob", source=SOURCE_V2)
    assert service.list(principal="alice", scope="mine")["total"] == 1
    assert service.list(principal="alice", scope="subordinates")["total"] == 1
    assert service.list(principal="bob", scope="shared")["total"] == 0

    metadata_update = service.update(
        strategy["strategy_ref"], {"visibility": "shared"}, principal="alice",
    )
    assert "source_code" not in metadata_update["strategy"]["current_revision"]
    service.grant(strategy["strategy_ref"], "bob", principal="alice")
    assert service.list(principal="bob", scope="shared")["total"] == 1
    old_revision = strategy["current_revision"]["revision_ref"]
    updated = service.update(
        strategy["strategy_ref"],
        {"source_code": SOURCE_V2},
        principal="alice",
    )["strategy"]
    assert updated["current_revision"]["revision_ref"] != old_revision
    assert len(updated["revisions"]) == 2
    assert service.get_revision(
        strategy["strategy_ref"], old_revision, principal="bob",
    )["revision"]["source_code"] == SOURCE


def test_strategy_reads_can_omit_source_and_updates_are_atomic(tmp_path: Path) -> None:
    service = library(tmp_path)
    strategy = create_strategy(service)
    current_ref = strategy["current_revision"]["revision_ref"]

    summary = service.get(
        strategy["strategy_ref"], principal="alice", include_source=False,
    )["strategy"]
    assert "source_code" not in summary["current_revision"]

    with pytest.raises(KeyError):
        service.store.update_entry_with_revision(
            strategy["strategy_ref"],
            name="partially changed",
            description="should roll back",
            visibility="public",
            expected_revision_ref=current_ref,
            revision={"source_sha256": "missing-fields"},
        )
    unchanged = service.get(strategy["strategy_ref"], principal="alice")["strategy"]
    assert unchanged["name"] == strategy["name"]
    assert unchanged["visibility"] == strategy["visibility"]
    assert unchanged["current_revision"]["revision_ref"] == current_ref


def test_library_list_pages_visible_rows_at_the_database_boundary(tmp_path: Path) -> None:
    service = library(tmp_path)
    mine = create_strategy(service)
    public = create_strategy(service, owner="bob", visibility="public")
    create_strategy(service, owner="carol")

    first_page = service.list(principal="alice", scope="all", page=1, limit=1)
    second_page = service.list(principal="alice", scope="all", page=2, limit=1)

    assert first_page["total"] == 2
    assert first_page["total_pages"] == 2
    assert len(first_page["items"]) == 1
    assert len(second_page["items"]) == 1
    assert {
        first_page["items"][0]["strategy_ref"],
        second_page["items"][0]["strategy_ref"],
    } == {mine["strategy_ref"], public["strategy_ref"]}


def test_configuration_inline_sources_are_deduplicated(tmp_path: Path) -> None:
    payload = {"shared": {}, "analyses": {"backtest": {}}}
    first = configuration_strategies.add_inline(
        payload, name="Temporary", source_code=SOURCE, entrypoint="Demo",
        target_strategy_id="group-1",
    )
    second = configuration_strategies.add_inline(
        payload, name="Same source", source_code=SOURCE, entrypoint="Demo",
        target_strategy_id="group-2",
    )
    configuration_strategies.validate(payload)
    assert first["strategy"]["temp_ref"] == second["strategy"]["temp_ref"]
    assert len(configuration_strategies.view(payload)["strategies"]) == 1
    compiled = compile_configuration_strategies(payload, owner="alice")
    assert len(compiled["transient_strategy_sources"]) == 1
    assert len(compiled["strategy_specs"]) == 2
    assert {item["strategy_kind"] for item in _normalize(compiled)} == {"custom"}


def test_library_binding_freezes_the_selected_revision(tmp_path: Path) -> None:
    service = library(tmp_path)
    strategy = create_strategy(service)
    old_revision = strategy["current_revision"]["revision_ref"]
    service.update(strategy["strategy_ref"], {"source_code": SOURCE_V2}, principal="alice")
    payload = {"shared": {}, "analyses": {"backtest": {}}}
    configuration_strategies.add_library(
        payload,
        strategy_ref=strategy["strategy_ref"],
        revision_ref=old_revision,
        target_strategy_id="group-1",
    )
    configuration_strategies.validate(payload)
    compiled = compile_configuration_strategies(
        payload, owner="alice", library=service,
    )
    assert compiled["transient_strategy_sources"][0]["source_code"] == SOURCE
    normalized = _normalize(compiled)[0]
    assert normalized["strategy_kind"] == "library"
    assert normalized["revision_ref"] == old_revision
    assert normalized["source"].startswith("profile:strategies/frozen/")


def _normalize(compiled: dict) -> list[dict]:
    from server.services.strategy_plans import normalize_strategy_plan

    paths = [item["path"] for item in compiled["transient_strategy_sources"]]
    return normalize_strategy_plan(compiled["strategy_specs"], uploaded_paths=paths)
