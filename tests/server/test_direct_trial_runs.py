from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import orjson
import pytest
import settings as Settings

from server.services import direct_trial_plan_registry, research_runs
from server.services.direct_trial_plans import create_binding
from server.services.research_run_identity import RUN_SPEC_VERSION, hash_run_spec
from server.services.research_sample_identity import (
    derive_sample_identity,
)
from tests.server.trial_plan_fixtures import run_spec, semantic_hash, trial_plan


def test_direct_trial_run_does_not_require_a_graph_branch(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "direct-run.sqlite")
    run_spec_value = run_spec()
    run_hash = semantic_hash(run_spec_value)
    binding = create_binding(
        trial_plan=trial_plan(run_hash),
        run_spec_hash=run_hash,
        trial_role="selection",
        comparison_id="main-comparison",
    )
    direct_trial_plan_registry.save(owner="alice", binding=binding)

    run = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=run_spec_value,
        trial_binding=binding,
    )

    assert run["trial_plan_hash"] == binding["trial_plan_hash"]
    assert run["graph_instance_id"] == ""
    assert run["graph_branch_id"] == ""
    assert run["graph_execution_node"] == ""


def test_direct_trial_run_persists_its_report_parent(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "direct-report.sqlite")
    run_spec_value = run_spec()
    run_hash = semantic_hash(run_spec_value)
    binding = create_binding(
        trial_plan=trial_plan(run_hash),
        run_spec_hash=run_hash,
        trial_role="selection",
        comparison_id="main-comparison",
    )
    direct_trial_plan_registry.save(owner="alice", binding=binding)
    report_binding = {
        "binding_origin": "agent_direct",
        "profile_ref": "profile:maxa",
        "work_package_ref": "work-package:package-1",
        "branch_id": "branch-1",
        "report_id": "report-package-1-branch-1",
        "report_generation": 7,
        "report_head_hash": "b" * 64,
        "report_parent_id": "direct-trials",
    }

    created = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=run_spec_value,
        trial_binding=binding,
        report_binding=report_binding,
    )
    loaded = research_runs.load_run(run_id=created["run_id"], owner="alice")

    assert created["report_binding"]["report_parent_id"] == "direct-trials"
    assert loaded["report_binding"] == created["report_binding"]


def test_direct_trial_run_rejects_an_unregistered_binding(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        Settings, "CACHE_DB_PATH", tmp_path / "unregistered-direct.sqlite",
    )
    run_spec_value = run_spec()
    run_hash = semantic_hash(run_spec_value)
    binding = create_binding(
        trial_plan=trial_plan(run_hash),
        run_spec_hash=run_hash,
        trial_role="selection",
        comparison_id="main-comparison",
    )

    with pytest.raises(ValueError, match="not registered"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="configuration-1",
            configuration_revision=1,
            run_spec=run_spec_value,
            trial_binding=binding,
        )


def _registered_direct_stage(
    *,
    run_spec_value: dict,
    version: int,
    role: str,
) -> dict:
    run_hash = semantic_hash(run_spec_value)
    plan = trial_plan(run_hash)
    plan.update({
        "schema_version": 2,
        "trial_plan_id": f"direct-plan-{version}",
        "version": version,
        "sample_roles": [{
            "sample_ref": f"{role}-{version}",
            "sample_hash": derive_sample_identity(run_spec_value)["sample_hash"],
            "role": role,
            "run_spec_hashes": [run_hash],
        }],
        "comparisons": [{
            "comparison_id": f"comparison-{version}",
            "members": [{"run_spec_hash": run_hash, "trial_role": role}],
        }],
    })
    binding = create_binding(
        trial_plan=plan,
        run_spec_hash=run_hash,
        trial_role=role,
        comparison_id=f"comparison-{version}",
    )
    direct_trial_plan_registry.save(owner="alice", binding=binding)
    return binding


def test_direct_trial_run_rejects_partial_protected_sample_overlap(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "direct-overlap.sqlite")
    product_a = "Product/Futures/CNFutures/_products/AP.CZC"
    product_b = "Product/Futures/CNFutures/_products/SI.GFE"
    product_c = "Product/Futures/CNFutures/_products/RB.SHF"

    selection_spec = run_spec()
    selection_spec["configuration"]["analyses"]["ic"]["paths"] = [
        product_a, product_b,
    ]
    selection_binding = _registered_direct_stage(
        run_spec_value=selection_spec,
        version=1,
        role="selection",
    )
    research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-selection",
        configuration_revision=1,
        run_spec=selection_spec,
        trial_binding=selection_binding,
    )

    confirmation_spec = run_spec()
    confirmation_spec["configuration"]["analyses"]["ic"]["paths"] = [
        product_b, product_c,
    ]
    confirmation_binding = _registered_direct_stage(
        run_spec_value=confirmation_spec,
        version=2,
        role="confirmation",
    )

    with pytest.raises(ValueError, match="already exposed"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="configuration-confirmation",
            configuration_revision=1,
            run_spec=confirmation_spec,
            trial_binding=confirmation_binding,
        )


def test_direct_protected_run_requires_concrete_frozen_product_members(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        Settings, "CACHE_DB_PATH", tmp_path / "direct-unproven-scope.sqlite",
    )
    spec = run_spec()
    run_hash = semantic_hash(spec)
    plan = trial_plan(run_hash)
    plan.update({
        "schema_version": 2,
        "sample_roles": [{
            "sample_ref": "confirmation",
            "sample_hash": derive_sample_identity(spec)["sample_hash"],
            "role": "confirmation",
            "run_spec_hashes": [run_hash],
        }],
        "comparisons": [{
                "comparison_id": "main-comparison",
                "members": [{
                    "run_spec_hash": run_hash,
                    "trial_role": "confirmation",
                }],
            }],
    })
    binding = create_binding(
        trial_plan=plan,
        run_spec_hash=run_hash,
        trial_role="confirmation",
        comparison_id="main-comparison",
    )
    direct_trial_plan_registry.save(owner="alice", binding=binding)

    with pytest.raises(ValueError, match="exact frozen product-membership"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="configuration-confirmation",
            configuration_revision=1,
            run_spec=spec,
            trial_binding=binding,
        )


def test_concurrent_protected_runs_cannot_bypass_overlap_check(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        Settings, "CACHE_DB_PATH", tmp_path / "direct-concurrent-overlap.sqlite",
    )
    product_a = "Product/Futures/CNFutures/_products/AP.CZC"
    product_b = "Product/Futures/CNFutures/_products/SI.GFE"
    product_c = "Product/Futures/CNFutures/_products/RB.SHF"
    specs = []
    bindings = []
    product_sets = ([product_a, product_b], [product_b, product_c])
    for version, paths in enumerate(product_sets, 1):
        spec = run_spec()
        spec["configuration"]["analyses"]["ic"]["paths"] = list(paths)
        specs.append(spec)
        bindings.append(
            _registered_direct_stage(
                run_spec_value=spec,
                version=version,
                role="confirmation",
            )
        )
    research_runs.ensure_schema()
    barrier = Barrier(2)

    def create_concurrently(index: int) -> str:
        barrier.wait(timeout=10)
        try:
            research_runs.create_run(
                owner="alice",
                workspace_id="workspace-1",
                configuration_id=f"configuration-{index}",
                configuration_revision=1,
                run_spec=specs[index],
                trial_binding=bindings[index],
            )
            return "created"
        except ValueError as exc:
            assert "already exposed" in str(exc)
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(create_concurrently, range(2)))

    assert sorted(outcomes) == ["created", "rejected"]


def test_run_spec_persistence_preserves_semantic_field_order(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "ordered-run.sqlite")
    run_spec_value = {
        "run_spec_version": RUN_SPEC_VERSION,
        "workspace_id": "workspace-1",
        "configuration_revision": 3,
        "analyses": ["backtest"],
        "configuration": {"shared": {}, "analyses": {"backtest": {}}},
        "retention_mode": "summary",
    }

    created = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=3,
        run_spec=run_spec_value,
    )
    loaded = research_runs.load_run(run_id=created["run_id"], owner="alice")
    stored = research_runs.load_run_spec(
        run_spec_hash=created["run_spec_hash"], owner="alice",
    )

    assert list(loaded["run_spec"]) == list(run_spec_value)
    assert list(stored["run_spec"]) == list(run_spec_value)
    assert list(orjson.loads(stored["complete_parameters_json"])) == list(run_spec_value)


def test_run_spec_hash_is_order_independent() -> None:
    first = {
        "run_spec_version": RUN_SPEC_VERSION,
        "workspace_id": "workspace-1",
        "analyses": ["ic"],
    }
    reordered = {
        "analyses": ["ic"],
        "workspace_id": "workspace-1",
        "run_spec_version": RUN_SPEC_VERSION,
    }

    assert hash_run_spec(first) == hash_run_spec(reordered)


@pytest.mark.parametrize(
    "version", [None, 1, RUN_SPEC_VERSION - 1, RUN_SPEC_VERSION + 1],
)
def test_run_creation_rejects_unsupported_run_spec_versions(
    tmp_path, monkeypatch, version,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / f"version-{version}.sqlite")
    run_spec_value = {"workspace_id": "workspace-1", "analyses": ["ic"]}
    if version is not None:
        run_spec_value["run_spec_version"] = version

    with pytest.raises(ValueError, match="unsupported run_spec_version"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="configuration-1",
            configuration_revision=1,
            run_spec=run_spec_value,
        )
