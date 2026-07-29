from base64 import urlsafe_b64encode
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.local_profile import new_local_profile
from tools.cli.release.research_reporting.authoring.declared_links import (
    DeclaredReportReference,
)
from tools.cli.release.research_reporting.references.authority import (
    validate_declared_reference,
)
from tools.cli.release.research_reporting.references.factor_git import (
    validate_factor_reference,
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
        kind="factor_family",
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
            kind="factor_family",
            target_ref=target_ref,
            roots={"profile-maxa": repository},
        )


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
    profile["server"] = {"base_url": "http://127.0.0.1:8142"}

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
            return {field: object_id, "status": "open"}

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
