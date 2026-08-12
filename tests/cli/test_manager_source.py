from __future__ import annotations

from pathlib import Path

from tools.cli.manager import source


def test_commit_source_cache_lives_below_primary_repository(
    tmp_path: Path, monkeypatch,
) -> None:
    repository = tmp_path / "Codes"
    worktree = repository / ".workspace" / "fix" / "issue-141"
    (worktree / "server/manager").mkdir(parents=True)
    (worktree / "server/manager" / "app.py").write_text(
        "# manager\n", encoding="utf-8",
    )
    revision = "a" * 40

    monkeypatch.setattr(source, "_repository_root", lambda _: repository)

    def check_output(command, **_kwargs):
        if command[1:3] == ["rev-parse", "--verify"]:
            return revision + "\n"
        raise AssertionError(command)

    def run(command, **_kwargs):
        checkout = Path(command[-2])
        (checkout / "server/manager").mkdir(parents=True)
        (checkout / "server/manager" / "app.py").write_text(
            "# manager\n", encoding="utf-8",
        )

    monkeypatch.setattr(source.subprocess, "check_output", check_output)
    monkeypatch.setattr(source.subprocess, "run", run)

    resolved = source.resolve_manager_source(
        worktree,
        source_mode="git-commit",
        source_revision=revision,
    )

    assert resolved == repository / ".workspace" / "manager-sources" / revision
