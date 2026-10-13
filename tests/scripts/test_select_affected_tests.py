from pathlib import Path
import subprocess

from scripts import select_affected_tests as selector


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def test_known_module_selects_cross_module_consumers():
    mode, targets = selector.select({"tools/cli/release/research_reporting/tree.py"})
    assert mode == "SCOPED"
    assert "tests/cli" in targets
    assert "tests/release" in targets
    assert "tests/server" in targets


def test_skill_change_checks_activation_and_skill_tests():
    assert selector.select({"skills/factortester-research-skill/SKILL.md"}) == (
        "SCOPED",
        ["tests/release/test_bundled_runtime_activation.py", "tests/skills"],
    )


def test_shared_and_unclassified_paths_fail_closed():
    assert selector.select({"environment.yml"}) == ("FULL", [])
    assert selector.select({"tools/parameters/base.py"}) == ("FULL", [])
    assert selector.select({"tools/cli/app.py", "mystery/new.py"}) == ("FULL", [])


def test_docs_only_skips_and_deleted_test_falls_back_to_module():
    assert selector.select({"docs/adr/new.md"}) == ("SKIP", [])
    assert selector.select({"tests/scripts/support.py"}) == ("SCOPED", ["tests/scripts"])
    assert selector.select({"tests/server/test_nonexistent_deleted.py"}) == (
        "SCOPED", ["tests/server"],
    )


def test_rename_considers_both_paths():
    paths = selector.paths_from_name_status(
        b"R100\0tools/cli/old.py\0tools/parameters/new.py\0"
    )
    assert paths == {"tools/cli/old.py", "tools/parameters/new.py"}
    assert selector.select(paths) == ("FULL", [])


def test_staged_and_push_ranges_are_separate(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "tools/cli").mkdir(parents=True)
    (repo / "tools/cli/app.py").write_text("original\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "-f", "origin/feat", base)
    (repo / "tools/cli/app.py").write_text("pushed\n")
    _git(repo, "commit", "-qam", "outgoing")
    head = _git(repo, "rev-parse", "HEAD")
    (repo / "tools/factors").mkdir(parents=True)
    (repo / "tools/factors/new.py").write_text("staged\n")
    _git(repo, "add", ".")
    monkeypatch.setattr(selector, "ROOT", repo)

    assert selector.staged_paths() == {"tools/factors/new.py"}
    assert selector.pushed_paths(f"refs/heads/feat {head} refs/heads/feat {base}\n") == {
        "tools/cli/app.py"
    }
    assert selector.pushed_paths(f"refs/heads/new {head} refs/heads/new {selector.ZERO_SHA}\n") == {
        "tools/cli/app.py"
    }
    assert selector.pushed_paths(f"refs/heads/feat {base} refs/heads/feat {base}\n") == set()
