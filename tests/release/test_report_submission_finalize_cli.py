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
    receipt = authoring / "submission-receipts" / "1.json"
    assert receipt.is_file()
    package = workspace_root / "research" / "wp"
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
    assert (authoring / "submission-receipts" / "1.json").is_file()

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
    assert (authoring / "submission-receipts" / "1.json").is_file()

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
    receipts = sorted(
        path.name for path in (authoring / "submission-receipts").glob("1*.json")
    )
    assert "1.json" in receipts
    assert len(receipts) == 2
    assert any(name.startswith("1-") for name in receipts)


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
