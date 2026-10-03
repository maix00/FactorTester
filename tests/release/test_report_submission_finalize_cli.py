from __future__ import annotations

import json
import subprocess

import pytest
from click.testing import CliRunner

from tests.release.test_report_submission_cli import _args, _scope
from tools.cli.commands import (
    research_report_authoring,
    research_report_component,
    research_report_component_write,
    research_report_inspection,
    research_report_submission_finalize,
)
from tools.cli.commands.research_report import report as report_cli
from tools.cli.release.research_reporting.authoring.submission_begin import (
    begin_submission,
)
from tools.cli.release.research_reporting.authoring.submission_pending import (
    digest,
)
from tools.cli.release.research_reporting.authoring.submission_receipts import (
    receipt_count,
)
from tools.cli.release.research_reporting.authoring.tree_paths import (
    report_tree_paths,
)


def _patch_root(monkeypatch: pytest.MonkeyPatch, client_root) -> None:
    for module in (
        research_report_authoring,
        research_report_component,
        research_report_inspection,
    ):
        monkeypatch.setattr(
            module, "load_profile_root", lambda _path: client_root,
        )


def _add_args(*, sequence: int | None = None) -> list[str]:
    value = [
        "add", *_args(), "--component-id", "finding", "--kind", "chapter",
        "--title", "结论", "--body", "有效正文", "--json",
    ]
    if sequence is not None:
        value.extend(["--submission-sequence", str(sequence)])
    return value


@pytest.mark.parametrize(
    ("attribute", "diagnostic_code"),
    [
        ("persist_descriptor", "report.submission.descriptor_failed"),
        ("commit_branch_authoring", "report.submission.git_failed"),
    ],
)
def test_finalize_failure_is_resumable_and_blocks_next_generation(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
    attribute: str, diagnostic_code: str,
) -> None:
    client_root, workspace_root = _scope(tmp_path)
    _patch_root(monkeypatch, client_root)
    runner = CliRunner()
    module = research_report_submission_finalize
    original = getattr(module, attribute)
    monkeypatch.setattr(
        module, attribute,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(f"{attribute} failed")
        ),
    )

    failed = runner.invoke(report_cli, _add_args())
    value = json.loads(failed.output)
    assert failed.exit_code == 1
    assert value["status"] == "published_pending_finalize"
    assert value["submission_sequence"] == 1
    assert value["diagnostics"][0]["code"] == diagnostic_code
    authoring = (
        workspace_root / "research" / "wp"
        / "branches" / "main" / "authoring"
    )
    assert json.loads((authoring / "HEAD.json").read_text())["generation"] == 1
    assert json.loads(
        (authoring / "pending-submission.json").read_text()
    )["phase"] == "published"

    unrelated = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "other", "--kind", "chapter",
        "--title", "其他", "--json",
    ])
    assert json.loads(unrelated.output)["status"] == "published_pending_finalize"

    monkeypatch.setattr(module, attribute, original)
    accepted = runner.invoke(report_cli, _add_args(sequence=1))
    assert accepted.exit_code == 0, accepted.output
    assert json.loads(accepted.output)["generation"] == 1
    assert not (authoring / "pending-submission.json").exists()
    package = workspace_root / "research" / "wp"
    assert receipt_count(report_tree_paths(package, "main")) == 1
    assert subprocess.run(
        ["git", "-C", str(package), "status", "--porcelain"],
        check=True, capture_output=True, text=True,
    ).stdout == ""


def test_finalized_receipt_replays_success_without_tree_mutation(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, workspace_root = _scope(tmp_path)
    _patch_root(monkeypatch, client_root)
    runner = CliRunner()
    original_output = research_report_component.output
    monkeypatch.setattr(
        research_report_component, "output",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("crash before CLI output")
        ),
    )
    interrupted = runner.invoke(report_cli, _add_args())
    assert interrupted.exit_code == 1
    authoring = (
        workspace_root / "research" / "wp"
        / "branches" / "main" / "authoring"
    )
    assert not (authoring / "pending-submission.json").exists()
    package = workspace_root / "research" / "wp"
    assert receipt_count(report_tree_paths(package, "main")) == 1

    monkeypatch.setattr(research_report_component, "output", original_output)
    monkeypatch.setattr(
        research_report_component_write, "add_branch_component",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("finalized replay must not mutate the tree")
        ),
    )
    replayed = runner.invoke(report_cli, _add_args(sequence=1))
    assert replayed.exit_code == 0, replayed.output
    assert json.loads(replayed.output)["generation"] == 1


def test_git_rewind_can_finalize_distinct_reused_generation(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, workspace_root = _scope(tmp_path)
    _patch_root(monkeypatch, client_root)
    runner = CliRunner()
    package = workspace_root / "research" / "wp"
    authoring = package / "branches" / "main" / "authoring"
    initial_commit = subprocess.run(
        ["git", "-C", str(package), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    first = runner.invoke(report_cli, _add_args())
    assert first.exit_code == 0, first.output
    assert receipt_count(report_tree_paths(package, "main")) == 1

    # A real Git revert restores the content-addressed HEAD but intentionally
    # leaves local durable receipts in place.
    subprocess.run(
        [
            "git", "-C", str(package), "checkout", initial_commit, "--",
            "branches/main/authoring",
        ],
        check=True,
    )
    second = runner.invoke(report_cli, [
        "add", *_args(), "--component-id", "different-finding",
        "--kind", "chapter", "--title", "不同结论", "--json",
    ])

    assert second.exit_code == 0, second.output
    assert json.loads(second.output)["generation"] == 1
    assert receipt_count(
        report_tree_paths(package, "main"), sequence=1,
    ) == 2


def test_finalize_pending_does_not_require_original_payload(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, workspace_root = _scope(tmp_path)
    _patch_root(monkeypatch, client_root)
    runner = CliRunner()
    module = research_report_submission_finalize
    original = module.commit_branch_authoring
    monkeypatch.setattr(
        module,
        "commit_branch_authoring",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("git failed")
        ),
    )
    failed = runner.invoke(report_cli, _add_args())
    assert failed.exit_code == 1
    monkeypatch.setattr(module, "commit_branch_authoring", original)

    finalized = runner.invoke(report_cli, [
        "finalize-pending", *_args(), "--json",
    ])

    assert finalized.exit_code == 0, finalized.output
    assert json.loads(finalized.output)["status"] == "finalized"
    pending = (
        workspace_root / "research" / "wp" / "branches" / "main"
        / "authoring" / "pending-submission.json"
    )
    assert not pending.exists()


def test_abandon_reserved_submission_restores_committed_sidecar_base(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, workspace_root = _scope(tmp_path)
    _patch_root(monkeypatch, client_root)
    runner = CliRunner()
    package = workspace_root / "research" / "wp"
    branch_root = package / "branches" / "main"
    authoring = branch_root / "authoring"
    sidecar_path = branch_root / "report-metadata.json"
    base = {"schema_version": 1, "generation": 0, "mode": "published"}
    next_value = {
        "schema_version": 1,
        "generation": 1,
        "mode": "draft",
    }
    sidecar_path.write_text(json.dumps(base, sort_keys=True) + "\n")
    subprocess.run(
        ["git", "-C", str(package), "add", "branches/main/report-metadata.json"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(package), "commit", "-m", "Add report metadata sidecar"],
        check=True, capture_output=True, text=True,
    )
    begin_submission(
        package_root=package,
        branch_id="main",
        requested_sequence=None,
        logical_identity={"kind": "metadata_update", "event_id": "metadata-draft"},
        payload={"mode": "draft"},
        sidecars=[{
            "path": "report-metadata.json",
            "base_generation": 0,
            "next_generation": 1,
            "next_hash": digest(next_value),
            "next_value": next_value,
        }],
    )
    sidecar_path.write_text(json.dumps(next_value, sort_keys=True) + "\n")
    subprocess.run(
        ["git", "-C", str(package), "add", "branches/main"], check=True,
    )
    subprocess.run(
        ["git", "-C", str(package), "commit", "-m", "Strand reserved metadata update"],
        check=True, capture_output=True, text=True,
    )

    abandoned = runner.invoke(report_cli, [
        "abandon-pending", *_args(), "--json",
    ])

    assert abandoned.exit_code == 0, abandoned.output
    value = json.loads(abandoned.output)
    assert value["status"] == "abandoned"
    assert value["submission_sequence"] == 1
    assert value["restored_sidecars"] == ["report-metadata.json"]
    assert json.loads(sidecar_path.read_text()) == base
    assert not (authoring / "pending-submission.json").exists()
    assert subprocess.run(
        ["git", "-C", str(package), "status", "--porcelain"],
        check=True, capture_output=True, text=True,
    ).stdout == ""


def test_abandon_published_submission_is_refused(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_root, _workspace_root = _scope(tmp_path)
    _patch_root(monkeypatch, client_root)
    runner = CliRunner()
    module = research_report_submission_finalize
    original = module.commit_branch_authoring
    monkeypatch.setattr(
        module,
        "commit_branch_authoring",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("git failed")
        ),
    )
    failed = runner.invoke(report_cli, _add_args())
    assert failed.exit_code == 1
    monkeypatch.setattr(module, "commit_branch_authoring", original)

    abandoned = runner.invoke(report_cli, [
        "abandon-pending", *_args(), "--json",
    ])

    assert abandoned.exit_code == 1
    assert "cannot be abandoned" in abandoned.output
