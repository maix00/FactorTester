from __future__ import annotations

import subprocess
from pathlib import Path

from tools.cli.release.research_reporting.git import commit_report_workspace


def _git(package: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(package), *args],
        check=True, capture_output=True, text=True,
    ).stdout


def test_pending_submission_is_ignored_and_never_committed(
    tmp_path: Path,
) -> None:
    package = tmp_path / "research" / "wp"
    pending = (
        package / "branches" / "main" / "authoring"
        / "pending-submission.json"
    )
    pending.parent.mkdir(parents=True)
    pending.write_text('{"submission_sequence":1}\n', encoding="utf-8")
    (package / "README.md").write_text("work package\n", encoding="utf-8")

    first = commit_report_workspace(package, message="Initialize")

    assert first["committed"] is True
    assert "pending-submission.json" in (
        package / ".gitignore"
    ).read_text(encoding="utf-8").splitlines()
    assert "pending-submission.json" not in _git(package, "ls-files")
    assert _git(
        package, "check-ignore", pending.relative_to(package).as_posix(),
    ).strip() == pending.relative_to(package).as_posix()

    pending.write_text('{"submission_sequence":2}\n', encoding="utf-8")
    _git(package, "add", "--force", pending.relative_to(package).as_posix())
    receipt = pending.parent / "submission.sqlite"
    receipt.write_bytes(b"local transaction state")
    _git(package, "add", "--force", receipt.relative_to(package).as_posix())
    assert "pending-submission.json" in _git(
        package, "diff", "--cached", "--name-only",
    )
    assert "submission.sqlite" in _git(
        package, "diff", "--cached", "--name-only",
    )
    (package / "README.md").write_text("updated\n", encoding="utf-8")
    second = commit_report_workspace(package, message="Update")

    assert second["committed"] is True
    assert "pending-submission.json" not in _git(
        package, "show", "--name-only", "--format=", "HEAD",
    )
    assert "submission.sqlite" not in _git(
        package, "show", "--name-only", "--format=", "HEAD",
    )
    assert _git(package, "status", "--porcelain") == ""
