import subprocess
from base64 import urlsafe_b64encode
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
from tools.cli.release.research_reporting.references.factor_git import (
    validate_factor_reference,
)
from tools.cli.release.research_reporting.references.factor_set_git import (
    create_factor_set_manifest,
    freeze_factor_set_reference,
)
from tools.cli.release.research_reporting.references.profile_revisions import (
    ProfileRevisionStore,
)


def test_factor_reference_validates_the_exact_commit_and_blob(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "factor-worktree"
    source = repository / "custom_factors" / "SgCPS.py"
    source.parent.mkdir(parents=True)
    source.write_text("factor = 1\n", encoding="utf-8")
    _commit(repository)
    revision = _git(repository, "rev-parse", "HEAD")
    blob = _git(repository, "rev-parse", "HEAD:custom_factors/SgCPS.py")
    target_ref = (
        "factor-family:v1:profile-maxa:"
        f"{_encoded('custom_factors/SgCPS.py')}:{_encoded('SgCPS')}:"
        f"{revision}:{blob}"
    )

    result = validate_factor_reference(
        kind="factor",
        target_ref=target_ref,
        roots={"profile-maxa": repository},
    )

    assert result["revision"] == revision
    assert result["blob_hash"] == blob
    assert result["relative_path"] == "custom_factors/SgCPS.py"
    assert result["identity"] == "SgCPS"


def test_factor_reference_rejects_a_fabricated_blob(tmp_path: Path) -> None:
    repository = tmp_path / "factor-worktree"
    source = repository / "custom_factors" / "SgCPS.py"
    source.parent.mkdir(parents=True)
    source.write_text("factor = 1\n", encoding="utf-8")
    _commit(repository)
    revision = _git(repository, "rev-parse", "HEAD")
    target_ref = (
        "factor-family:v1:profile-maxa:"
        f"{_encoded('custom_factors/SgCPS.py')}:{_encoded('SgCPS')}:"
        f"{revision}:{'0' * 40}"
    )

    with pytest.raises(ValueError, match="blob"):
        validate_factor_reference(
            kind="factor",
            target_ref=target_ref,
            roots={"profile-maxa": repository},
        )


def test_factor_set_reference_validates_its_members_and_manifest_blob(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "factor-worktree"
    source = repository / "custom_factors" / "SgCPS.py"
    source.parent.mkdir(parents=True)
    source.write_text("factor = 1\n", encoding="utf-8")
    _commit(repository)
    revision = _git(repository, "rev-parse", "HEAD")
    blob = _git(repository, "rev-parse", "HEAD:custom_factors/SgCPS.py")
    member_ref = (
        "factor:v1:profile-maxa:"
        f"{_encoded('custom_factors/SgCPS.py')}:{_encoded('SgCPS|N:20d')}:"
        f"{revision}:{blob}"
    )
    create_factor_set_manifest(
        repository=repository,
        scope="profile-maxa",
        set_id="momentum-column-2025",
        title_zh="2025年动量因子列",
        member_refs=[member_ref],
    )
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(repository),
        "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "-qm", "factor set",
    ], check=True)

    value = freeze_factor_set_reference(
        repository=repository,
        scope="profile-maxa",
        set_id="momentum-column-2025",
        roots={"profile-maxa": repository},
    )

    assert value["set_ref"] == (
        "factor-set:profile-maxa:momentum-column-2025"
    )
    assert value["member_refs"] == [member_ref]
    assert value["member_count"] == 1
    assert value["related_references"] == [{
        "relation": "集合成员",
        "kind": "factor",
        "target_ref": member_ref,
        "label": "SgCPS|N:20d",
        "data": {
            "scope": "profile-maxa",
            "relative_path": "custom_factors/SgCPS.py",
            "identity": "SgCPS|N:20d",
            "revision": revision,
            "blob_hash": blob,
        },
    }]

    client_root = tmp_path / "client"
    profile = new_local_profile(
        profile_id="maxa", display_name="MaxA",
        server_url="http://127.0.0.1:8141",
        workspace_root=tmp_path / "workspace",
    )
    profile["factor_workspace_binding"] = {
        "binding_id": "factor-maxa",
        "canonical_repo_ref": "local-factor-git:maxa",
        "base_commit": _git(repository, "rev-parse", "HEAD"),
        "branch": "research-maxa",
        "worktree_path": str(repository),
        "research_root": str(tmp_path / "workspace" / "research"),
        "git_common_dir": str(repository / ".git"),
        "owner_ref": "owner-1",
        "sync_policy": {
            "source_sync_enabled": False,
            "auto_push": False,
            "auto_merge": False,
        },
        "receipt_hash": "a" * 64,
        "receipt_ref": (tmp_path / "binding.json").resolve().as_uri(),
    }
    LocalProfileStore(client_root).save(profile)
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
    assert compact["member_hash"] == value["member_hash"]
    assert "member_refs" not in compact
    assert "related_references" not in compact
    assert "descriptor" not in compact


def test_factor_set_rejects_parameterized_family_members(tmp_path: Path) -> None:
    repository = tmp_path / "factor-worktree"
    source = repository / "custom_factors" / "SgCPS.py"
    source.parent.mkdir(parents=True)
    source.write_text("factor = 1\n", encoding="utf-8")
    _commit(repository)
    revision = _git(repository, "rev-parse", "HEAD")
    blob = _git(repository, "rev-parse", "HEAD:custom_factors/SgCPS.py")
    family_ref = (
        "factor-family:v1:profile-maxa:"
        f"{_encoded('custom_factors/SgCPS.py')}:{_encoded('SgCPS')}:"
        f"{revision}:{blob}"
    )

    with pytest.raises(ValueError, match="concrete factor:v1"):
        create_factor_set_manifest(
            repository=repository,
            scope="profile-maxa",
            set_id="invalid-family-set",
            title_zh="无效集合",
            member_refs=[family_ref],
        )


def test_large_factor_set_report_binding_keeps_only_frozen_identity(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "factor-worktree"
    source = repository / "custom_factors" / "Momentum.py"
    source.parent.mkdir(parents=True)
    source.write_text("factor = 1\n", encoding="utf-8")
    _commit(repository)
    revision = _git(repository, "rev-parse", "HEAD")
    blob = _git(repository, "rev-parse", "HEAD:custom_factors/Momentum.py")
    members = [
        (
            "factor:v1:profile-maxa:"
            f"{_encoded('custom_factors/Momentum.py')}:"
            f"{_encoded(f'Momentum|N:{index}m')}:{revision}:{blob}"
        )
        for index in range(1, 129)
    ]
    create_factor_set_manifest(
        repository=repository,
        scope="profile-maxa",
        set_id="momentum-column-128",
        title_zh="128成员动量因子集合",
        member_refs=members,
    )
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(repository),
        "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "-qm", "large factor set",
    ], check=True)
    frozen = freeze_factor_set_reference(
        repository=repository,
        scope="profile-maxa",
        set_id="momentum-column-128",
        roots={"profile-maxa": repository},
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


def test_profile_revision_freezes_configuration_not_research_history(
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
    profile["research_records"] = [{
        "record_id": "research-a", "title": "history", "status": "pending",
        "scope": {}, "factor_family_versions": [], "agent_id": "research-maxa",
        "created_at": 1.0, "updated_at": 1.0,
        "workspace_ref": "", "run_ref": "",
        "graph_instance_ref": "", "graph_branch_ref": "",
        "checkpoint_ref": "", "evidence_refs": [], "timeline_refs": [],
        "artifacts": [], "provenance": {},
    }]
    second = store.freeze(profile)

    assert first["target_ref"] == second["target_ref"]
    assert store.load(first["target_ref"])["profile_id"] == "maxa"


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


@pytest.mark.parametrize(
    ("kind", "target_ref", "object_type", "object_id", "field"),
    [
        (
            "obligation", "obligation:predictive-validity",
            "obligation", "predictive-validity", "obligation_id",
        ),
        (
            "claim", "claim:sgccs-survival",
            "claim", "sgccs-survival", "claim_id",
        ),
        (
            "task", "research-cycle-review:abc",
            "task", "research-cycle-review:abc", "task_ref",
        ),
    ],
)
def test_authority_validates_exact_branch_cycle_objects(
    tmp_path: Path,
    kind: str,
    target_ref: str,
    object_type: str,
    object_id: str,
    field: str,
) -> None:
    class Client:
        def get_research_cycle_object(
            self, instance_id, branch_id, requested_type, requested_id,
            *, trace_id=None,
        ):
            assert (instance_id, branch_id) == ("instance-1", "branch-1")
            assert (requested_type, requested_id) == (
                object_type, object_id,
            )
            assert trace_id is None
            return {
                field: object_id,
                "status": "open",
                "requirement_refs": ["data.required_fields"],
                "claim_ids": ["claim-related"],
                "evidence_refs": ["evidence:accepted"],
            }

    result = validate_declared_reference(
        reference=DeclaredReportReference(
            kind=kind, target_ref=target_ref, label="对象",
        ),
        scope=SimpleNamespace(
            client_root=tmp_path / "client",
            profile_id="maxa",
            profile={},
            package_root=tmp_path / "research" / "wp",
            branch_ref="graph-branch:instance-1:branch-1",
        ),
        client=Client(),
    )

    assert result["target_ref"] == target_ref
    assert result["data"][field] == object_id
    assert result["data"]["related_references"] == [{
        "relation": "要求",
        "kind": "entry_requirement",
        "target_ref": "requirement:data.required_fields",
        "label": "data.required_fields",
        "data": {},
    }, {
        "relation": "关联主张",
        "kind": "claim",
        "target_ref": "claim:claim-related",
        "label": "claim-related",
        "data": {},
    }, {
        "relation": "支持证据",
        "kind": "evidence",
        "target_ref": "evidence:accepted",
        "label": "accepted",
        "data": {},
    }]


def test_authority_requires_an_explicit_graph_branch_scope(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="graph branch"):
        validate_declared_reference(
            reference=DeclaredReportReference(
                kind="obligation",
                target_ref="obligation:predictive-validity",
                label="义务",
            ),
            scope=SimpleNamespace(
                client_root=tmp_path / "client",
                profile_id="maxa",
                profile={},
                package_root=tmp_path / "research" / "wp",
                branch_ref="report-branch:local",
            ),
            client=object(),
        )


def test_authority_validates_exact_current_node_check(
    tmp_path: Path,
) -> None:
    class Client:
        def get_current_graph_requirement(
            self, instance_id, branch_id, requirement_id,
        ):
            assert (instance_id, branch_id) == ("instance-1", "branch-1")
            assert requirement_id == "factor_semantics.expression_identity"
            return {
                "graph_ref": "factor-research@v10",
                "node_id": "hypothesis_preregistration",
                "requirement": {
                    "requirement_id": requirement_id,
                    "title_zh": "表达式身份",
                    "gate_policy": "required",
                },
            }

    result = validate_declared_reference(
        reference=DeclaredReportReference(
            kind="entry_requirement",
            target_ref=(
                "requirement:factor_semantics.expression_identity"
            ),
            label="节点检查",
        ),
        scope=SimpleNamespace(
            client_root=tmp_path / "client",
            profile_id="maxa",
            profile={},
            package_root=tmp_path / "research" / "wp",
            branch_ref="graph-branch:instance-1:branch-1",
        ),
        client=Client(),
    )

    assert result["data"] == {
        "graph_ref": "factor-research@v10",
        "node_id": "hypothesis_preregistration",
        "requirement_id": "factor_semantics.expression_identity",
        "title_zh": "表达式身份",
        "gate_policy": "required",
        "detail_ref": (
            "graph-requirement:factor_semantics.expression_identity"
        ),
    }


def test_authority_rejects_a_different_node_check(
    tmp_path: Path,
) -> None:
    class Client:
        def get_current_graph_requirement(self, *_args):
            return {
                "requirement": {"requirement_id": "data.scope"},
            }

    with pytest.raises(ValueError, match="exact requirement"):
        validate_declared_reference(
            reference=DeclaredReportReference(
                kind="entry_requirement",
                target_ref=(
                    "requirement:factor_semantics.expression_identity"
                ),
                label="节点检查",
            ),
            scope=SimpleNamespace(
                branch_ref="graph-branch:instance-1:branch-1",
            ),
            client=Client(),
        )


def test_authority_uses_immutable_catalog_for_historical_chapter(
    tmp_path: Path,
) -> None:
    class Client:
        def get_current_graph_requirement(self, *_args):
            raise KeyError("requirement is not active at current node")

        def get_research_graph_node_info(self, *_args):
            return {"graph": "factor-research@v10"}

        def list_research_graph_versions(self, graph_id):
            assert graph_id == "factor-research"
            return [{
                "version": 10,
                "requirement_catalog": {"requirements": [{
                    "requirement_id": (
                        "hypothesis_validity.mechanism_chain"
                    ),
                    "title_zh": "机制作用链",
                    "gate_policy": "required",
                }]},
            }]

    result = validate_declared_reference(
        reference=DeclaredReportReference(
            kind="entry_requirement",
            target_ref=(
                "requirement:hypothesis_validity.mechanism_chain"
            ),
            label="义务小类",
        ),
        scope=SimpleNamespace(
            branch_ref="graph-branch:instance-1:branch-1",
        ),
        client=Client(),
        allow_historical_entry_requirement=True,
    )

    assert result["data"] == {
        "graph_ref": "factor-research@v10",
        "authority_scope": "historical_graph_catalog",
        "requirement_id": "hypothesis_validity.mechanism_chain",
        "title_zh": "机制作用链",
        "gate_policy": "required",
        "detail_ref": (
            "graph-requirement:hypothesis_validity.mechanism_chain"
        ),
    }


def _encoded(value: str) -> str:
    return urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _commit(repository: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(repository),
        "-c", "user.name=Test",
        "-c", "user.email=test@example.com",
        "commit", "-qm", "factor",
    ], check=True)


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
