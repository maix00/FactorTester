from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.cli.release.local_profile import LocalProfileStore, new_local_profile
from tools.cli.release.research_reporting.authoring.declared_links import (
    DeclaredReportReference,
)
from tools.cli.release.research_reporting.authoring.tree_schema import (
    validate_binding,
)
from tools.cli.release.research_reporting.references.authority import (
    validate_declared_reference,
)
from tools.cli.release.research_reporting.references.factor_formula import (
    validate_factor_reference,
)
from tools.cli.release.research_reporting.references.factor_set_workspace import (
    create_factor_set_manifest,
    freeze_factor_set_reference,
)
from tools.cli.release.research_reporting.references.profile_revisions import (
    ProfileRevisionStore,
)
from tools.factors.formula_identity import freeze_factor_identity


def test_factor_reference_validates_an_opaque_formula_reference() -> None:
    factor = _factor("SgCPS|N:20d", "b")
    result = validate_factor_reference(
        kind="factor",
        target_ref=factor["ref"],
        roots={},
    )

    assert result == {
        "kind": "factor",
        "object_kind": "factor",
        "target_ref": factor["ref"],
    }


def test_factor_reference_rejects_legacy_git_identity() -> None:
    with pytest.raises(ValueError, match="v2"):
        validate_factor_reference(
            kind="factor",
            target_ref="factor:v1:profile-maxa:path:alias:commit:blob",
            roots={},
        )


def test_factor_set_reference_validates_complete_frozen_members(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "factor-worktree"
    member = _factor("SgCPS|N:20d", "b")
    create_factor_set_manifest(
        repository=repository,
        scope="profile-maxa",
        set_id="momentum-column-2025",
        title_zh="2025年动量因子列",
        members=[member],
    )

    value = freeze_factor_set_reference(
        repository=repository,
        scope="profile-maxa",
        set_id="momentum-column-2025",
    )

    assert value["target_ref"].startswith("factor-set:v2:")
    assert value["member_refs"] == [member["ref"]]
    assert value["member_count"] == 1
    assert value["related_references"] == [{
        "relation": "集合成员",
        "kind": "factor",
        "target_ref": member["ref"],
        "label": "SgCPS|N:20d",
        "data": member,
    }]

    client_root = tmp_path / "client"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
    )
    profile["factor_workspace_binding"] = {
        "worktree_path": str(repository),
    }
    compact = validate_declared_reference(
        reference=DeclaredReportReference(
            kind="factor", target_ref=value["target_ref"], label="动量集合",
        ),
        scope=SimpleNamespace(
            client_root=client_root,
            profile_id="maxa",
            profile=profile,
            package_root=tmp_path / "workspace" / "research" / "wp",
        ),
    )["data"]
    assert compact["member_count"] == 1
    assert compact["member_fingerprint"] == value["member_fingerprint"]
    assert "member_refs" not in compact
    assert "related_references" not in compact
    assert "descriptor" not in compact


def test_factor_set_rejects_duplicate_frozen_members(tmp_path: Path) -> None:
    repository = tmp_path / "factor-worktree"
    member = _factor("SgCPS|N:20d", "b")

    with pytest.raises(ValueError, match="unique"):
        create_factor_set_manifest(
            repository=repository,
            scope="profile-maxa",
            set_id="invalid-family-set",
            title_zh="无效集合",
            members=[member, member],
        )


def test_large_factor_set_report_binding_keeps_only_frozen_identity(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "factor-worktree"
    members = [
        _factor(f"Momentum|N:{index}m", f"{index:064x}")
        for index in range(1, 129)
    ]
    create_factor_set_manifest(
        repository=repository,
        scope="profile-maxa",
        set_id="momentum-column-128",
        title_zh="128成员动量因子集合",
        members=members,
    )
    frozen = freeze_factor_set_reference(
        repository=repository,
        scope="profile-maxa",
        set_id="momentum-column-128",
    )
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
    )
    profile["factor_workspace_binding"] = {
        "worktree_path": str(repository),
    }
    compact = validate_declared_reference(
        reference=DeclaredReportReference(
            kind="factor", target_ref=frozen["target_ref"],
            label="128成员动量因子集合",
        ),
        scope=SimpleNamespace(
            client_root=tmp_path / "client",
            profile_id="maxa",
            profile=profile,
            package_root=tmp_path / "workspace" / "research" / "wp",
        ),
    )["data"]

    binding = validate_binding({
        "binding_id": "reference-large-factor-set",
        "kind": "factor",
        "target_ref": frozen["target_ref"],
        "label": "128成员动量因子集合",
        "data": compact,
    })

    assert binding["data"]["member_count"] == 128
    assert "member_refs" not in binding["data"]
    assert "related_references" not in binding["data"]


def test_profile_revision_discards_legacy_research_history(
    tmp_path: Path,
) -> None:
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
    )
    store = ProfileRevisionStore(tmp_path / "client")

    profile["schema_version"] = 10
    profile["research_records"] = [{
        "record_id": "research-a", "title": "history", "status": "pending",
        "scope": {}, "factor_family_versions": [], "agent_id": "research-maxa",
        "created_at": 1.0, "updated_at": 1.0,
        "workspace_ref": "", "run_ref": "",
        "evidence_refs": [],
        "artifacts": [], "provenance": {},
    }]
    frozen = store.freeze(profile)

    assert "research_records" not in frozen["configuration"]
    assert store.load(frozen["target_ref"])["profile_id"] == "maxa"


def test_profile_revision_changes_when_configuration_changes(
    tmp_path: Path,
) -> None:
    profile = new_local_profile(
        profile_id="maxa",
        display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
    )
    store = ProfileRevisionStore(tmp_path / "client")
    first = store.freeze(profile)
    profile["display_name"] = "MaxA revised"

    second = store.freeze(profile)

    assert first["target_ref"] != second["target_ref"]


def test_authority_validates_profile_from_the_local_registry(
    tmp_path: Path,
) -> None:
    client_root = tmp_path / "client"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
    )
    LocalProfileStore(client_root).save(profile)
    scope = SimpleNamespace(
        client_root=client_root,
        profile_id="maxa",
        profile=profile,
        package_root=tmp_path / "workspace" / "research" / "wp",
    )

    result = validate_declared_reference(
        reference=DeclaredReportReference(
            kind="profile", target_ref="profile:maxa", label="MaxA",
        ),
        scope=scope,
    )

    assert result["data"]["profile_id"] == "maxa"
    assert result["data"]["display_name"] == "MaxA"


def test_authority_passes_an_exact_product_path_without_rewriting(
    tmp_path: Path,
) -> None:
    target_ref = "Product/Futures/CNFutures/_products/SI.GFE"

    class Client:
        def validate_report_reference(self, *, kind, target_ref):
            assert kind == "product"
            return {
                "kind": kind,
                "target_ref": target_ref,
                "object": {"entity_path": target_ref},
            }

    result = validate_declared_reference(
        reference=DeclaredReportReference(
            kind="product", target_ref=target_ref, label="工业硅",
        ),
        scope=SimpleNamespace(
            client_root=tmp_path / "client",
            profile_id="maxa",
            profile={},
            package_root=tmp_path / "research" / "wp",
        ),
        client=Client(),
    )

    assert result["target_ref"] == target_ref
    assert result["data"]["entity_path"] == target_ref


def test_authority_uses_client_connection_not_profile_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.cli.release.research_reporting.references import authority

    class Client:
        def validate_report_reference(self, *, kind, target_ref):
            return {
                "kind": kind,
                "target_ref": target_ref,
                "object": {"entity_path": target_ref},
            }

    monkeypatch.setattr(authority, "client_from_config", lambda: Client())
    scope = SimpleNamespace(
        client_root=tmp_path / "client",
        profile_id="maxa",
        # A stale endpoint must be ignored if an old caller still carries it.
        profile={"server": {"base_url": "http://127.0.0.1:1"}},
        package_root=tmp_path / "research" / "wp",
    )
    target_ref = "Product/Futures/CNFutures/_products/SI.GFE"

    result = validate_declared_reference(
        reference=DeclaredReportReference(
            kind="product", target_ref=target_ref, label="工业硅",
        ),
        scope=scope,
    )

    assert result["data"]["entity_path"] == target_ref


def test_authority_rejects_a_server_that_rewrites_the_reference(
    tmp_path: Path,
) -> None:
    class Client:
        def validate_report_reference(self, *, kind, target_ref):
            return {
                "kind": kind,
                "target_ref": "Product/Futures/_products/OTHER",
                "object": {},
            }

    with pytest.raises(ValueError, match="rewrote"):
        validate_declared_reference(
            reference=DeclaredReportReference(
                kind="product",
                target_ref="Product/Futures/CNFutures/_products/SI.GFE",
                label="工业硅",
            ),
            scope=SimpleNamespace(
                client_root=tmp_path / "client",
                profile_id="maxa",
                profile={},
                package_root=tmp_path / "research" / "wp",
            ),
            client=Client(),
        )


def _factor(alias: str, fingerprint: str) -> dict:
    family_alias = alias.split("|", 1)[0]
    params = dict(
        item.split(":", 1) for item in alias.split("|")[1:]
    )
    return freeze_factor_identity(
        owner_ref="profile:maxa",
        family_alias=family_alias,
        factor_alias=alias,
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint=(
            fingerprint * 64 if len(fingerprint) == 1 else fingerprint
        ),
        params=params,
    )
