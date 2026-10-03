from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import orjson
import pytest
import settings as Settings

from server.services import research_runs
from server.services.research_run_identity import RUN_SPEC_VERSION, hash_run_spec
from tests.server.trial_plan_fixtures import run_spec


def test_new_run_has_no_trial_plan_identity_or_empty_sentinels(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "direct-run.sqlite")
    run = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-1",
        configuration_revision=1,
        run_spec=run_spec(),
    )

    assert not any(key.startswith("trial_plan") for key in run)
    assert "trial_binding" not in run
    assert run["report_binding"] is None


def test_unbound_validation_run_persists_an_open_sample_use(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        Settings, "CACHE_DB_PATH", tmp_path / "open-sample-use.sqlite",
    )
    run_spec_value = run_spec()
    sample_use = {
        "schema_version": 1,
        "purpose": "validation",
        "protection": "open",
    }

    created = research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-validation",
        configuration_revision=1,
        run_spec=run_spec_value,
        sample_use=sample_use,
    )
    loaded = research_runs.load_run(run_id=created["run_id"], owner="alice")

    assert "trial_plan_hash" not in created
    assert created["sample_use"]["purpose"] == "validation"
    assert created["sample_use"]["protection"] == "open"
    assert (
        created["sample_use"]["sample_hash"]
        == created["sample_identity_hash"]
    )
    assert loaded["sample_use"] == created["sample_use"]
    assert "trial_plan_hash" not in loaded


def test_omitting_sample_use_cannot_reuse_a_sealed_sample(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        Settings, "CACHE_DB_PATH", tmp_path / "sealed-sample-use.sqlite",
    )
    product = "Product/Futures/CNFutures/_products/AP.CZC"
    candidate_a = run_spec()
    candidate_a["candidate"] = "a"
    candidate_a["configuration"]["analyses"]["ic"]["paths"] = [product]
    candidate_b = run_spec()
    candidate_b["candidate"] = "b"
    candidate_b["configuration"]["analyses"]["ic"]["paths"] = [product]
    hash_a = hash_run_spec(candidate_a)
    hash_b = hash_run_spec(candidate_b)
    sealed = {
        "schema_version": 1,
        "purpose": "confirmation",
        "protection": "sealed",
        "comparison_id": "duration-finalists",
        "member_run_spec_hashes": [hash_a, hash_b],
    }

    research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-a",
        configuration_revision=1,
        run_spec=candidate_a,
        sample_use=sealed,
    )

    with pytest.raises(ValueError, match="sealed sample"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="configuration-b",
            configuration_revision=1,
            run_spec=candidate_b,
        )


def test_frozen_sealed_comparison_accepts_each_declared_run_once(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        Settings, "CACHE_DB_PATH", tmp_path / "sealed-comparison.sqlite",
    )
    product = "Product/Futures/CNFutures/_products/AP.CZC"
    candidates = []
    for label in ("a", "b"):
        spec = run_spec()
        spec["candidate"] = label
        spec["configuration"]["analyses"]["ic"]["paths"] = [product]
        candidates.append(spec)
    hashes = [hash_run_spec(spec) for spec in candidates]
    sample_use = {
        "schema_version": 1,
        "purpose": "confirmation",
        "protection": "sealed",
        "comparison_id": "duration-finalists",
        "member_run_spec_hashes": hashes,
    }

    runs = [
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id=f"configuration-{index}",
            configuration_revision=1,
            run_spec=spec,
            sample_use=sample_use,
        )
        for index, spec in enumerate(candidates)
    ]

    assert [item["run_spec_hash"] for item in runs] == hashes
    assert runs[0]["sample_use"]["sample_use_hash"] == (
        runs[1]["sample_use"]["sample_use_hash"]
    )


def test_frozen_sealed_comparison_rejects_a_duplicate_candidate(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        Settings, "CACHE_DB_PATH", tmp_path / "duplicate-sealed-candidate.sqlite",
    )
    spec = run_spec()
    product = "Product/Futures/CNFutures/_products/AP.CZC"
    spec["configuration"]["analyses"]["ic"]["paths"] = [product]
    digest = hash_run_spec(spec)
    sample_use = {
        "schema_version": 1,
        "purpose": "confirmation",
        "protection": "sealed",
        "comparison_id": "single-candidate",
        "member_run_spec_hashes": [digest],
    }
    request = {
        "owner": "alice",
        "workspace_id": "workspace-1",
        "configuration_revision": 1,
        "run_spec": spec,
        "sample_use": sample_use,
    }
    research_runs.create_run(
        configuration_id="configuration-1", **request,
    )

    with pytest.raises(ValueError, match="already been exposed"):
        research_runs.create_run(
            configuration_id="configuration-2", **request,
        )


def test_additional_candidate_is_recorded_as_open_exposure_and_contaminates_seal(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        Settings, "CACHE_DB_PATH", tmp_path / "additional-open-exposure.sqlite",
    )
    product = "Product/Futures/CNFutures/_products/AP.CZC"
    candidates = []
    for label in ("a", "b", "c"):
        spec = run_spec()
        spec["candidate"] = label
        spec["configuration"]["analyses"]["ic"]["paths"] = [product]
        candidates.append(spec)
    hashes = [hash_run_spec(spec) for spec in candidates]
    sealed = {
        "schema_version": 1,
        "purpose": "confirmation",
        "protection": "sealed",
        "comparison_id": "declared-finalists",
        "member_run_spec_hashes": hashes[:2],
    }
    common = {
        "owner": "alice",
        "workspace_id": "workspace-1",
        "configuration_revision": 1,
    }
    research_runs.create_run(
        configuration_id="configuration-a",
        run_spec=candidates[0],
        sample_use=sealed,
        **common,
    )
    exploratory = research_runs.create_run(
        configuration_id="configuration-c",
        run_spec=candidates[2],
        sample_use={
            "schema_version": 1,
            "purpose": "selection",
            "protection": "open",
        },
        **common,
    )

    assert exploratory["sample_use"]["protection"] == "open"
    assert exploratory["sample_use"]["sample_use_hash"]
    with pytest.raises(ValueError, match="already exposed"):
        research_runs.create_run(
            configuration_id="configuration-b",
            run_spec=candidates[1],
            sample_use=sealed,
            **common,
        )


def test_concurrent_sealed_sample_claims_are_atomic(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        Settings, "CACHE_DB_PATH", tmp_path / "concurrent-sample-seals.sqlite",
    )
    product_a = "Product/Futures/CNFutures/_products/AP.CZC"
    product_b = "Product/Futures/CNFutures/_products/SI.GFE"
    product_c = "Product/Futures/CNFutures/_products/RB.SHF"
    specs = []
    uses = []
    for index, paths in enumerate(([product_a, product_b], [product_b, product_c])):
        spec = run_spec()
        spec["configuration"]["analyses"]["ic"]["paths"] = list(paths)
        digest = hash_run_spec(spec)
        specs.append(spec)
        uses.append({
            "schema_version": 1,
            "purpose": "confirmation",
            "protection": "sealed",
            "comparison_id": f"concurrent-{index}",
            "member_run_spec_hashes": [digest],
        })
    barrier = Barrier(2)

    def submit(index: int) -> str:
        barrier.wait(timeout=10)
        try:
            research_runs.create_run(
                owner="alice",
                workspace_id="workspace-1",
                configuration_id=f"configuration-{index}",
                configuration_revision=1,
                run_spec=specs[index],
                sample_use=uses[index],
            )
        except ValueError as exc:
            assert "sealed sample" in str(exc)
            return "rejected"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, range(2)))

    assert sorted(outcomes) == ["created", "rejected"]


def test_unprovable_legacy_sealed_scope_fails_closed(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(
        Settings, "CACHE_DB_PATH", tmp_path / "unknown-sealed-scope.sqlite",
    )
    product = "Product/Futures/CNFutures/_products/AP.CZC"
    first = run_spec()
    first["configuration"]["analyses"]["ic"]["paths"] = [product]
    first_hash = hash_run_spec(first)
    research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="configuration-a",
        configuration_revision=1,
        run_spec=first,
        sample_use={
            "schema_version": 1,
            "purpose": "confirmation",
            "protection": "sealed",
            "comparison_id": "legacy-range",
            "member_run_spec_hashes": [first_hash],
        },
    )
    with research_runs._connect() as conn:
        conn.execute(
            "UPDATE research_runs SET sample_start='', sample_end='' "
            "WHERE owner='alice'"
        )
    next_run = run_spec()
    next_run["configuration"]["analyses"]["ic"]["paths"] = [product]

    with pytest.raises(ValueError, match="scope cannot be proven"):
        research_runs.create_run(
            owner="alice",
            workspace_id="workspace-1",
            configuration_id="configuration-b",
            configuration_revision=1,
            run_spec=next_run,
        )


def test_sealed_sample_protection_is_owner_scoped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        Settings, "CACHE_DB_PATH", tmp_path / "owner-scoped-seal.sqlite",
    )
    product = "Product/Futures/CNFutures/_products/AP.CZC"
    first = run_spec()
    first["configuration"]["analyses"]["ic"]["paths"] = [product]
    digest = hash_run_spec(first)
    seal = {
        "schema_version": 1,
        "purpose": "confirmation",
        "protection": "sealed",
        "comparison_id": "alice-only",
        "member_run_spec_hashes": [digest],
    }
    research_runs.create_run(
        owner="alice",
        workspace_id="workspace-1",
        configuration_id="alice-run",
        configuration_revision=1,
        run_spec=first,
        sample_use=seal,
    )

    other_owner = research_runs.create_run(
        owner="bob",
        workspace_id="workspace-1",
        configuration_id="bob-run",
        configuration_revision=1,
        run_spec=first,
    )

    assert other_owner["owner"] == "bob"


def test_run_without_trial_plan_persists_its_report_parent(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", tmp_path / "direct-report.sqlite")
    report_binding = {
        "profile_ref": "profile:maxa",
        "report_workspace_id": "workspace-package-1",
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
        run_spec=run_spec(),
        report_binding=report_binding,
    )
    loaded = research_runs.load_run(run_id=created["run_id"], owner="alice")

    assert created["report_binding"]["report_parent_id"] == "direct-trials"
    assert loaded["report_binding"] == created["report_binding"]


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
