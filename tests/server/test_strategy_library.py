from __future__ import annotations

from pathlib import Path

import pytest

from server.services import configuration_strategies
from server.services.strategy_bindings import compile_configuration_strategies
from server.services.strategy_library import StrategyLibraryService
from server.services.strategy_library.model import inspect_source


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

    service.update(strategy["strategy_ref"], {"visibility": "shared"}, principal="alice")
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
