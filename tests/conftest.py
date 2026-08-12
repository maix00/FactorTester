from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SKILL = ROOT / "skills/cli-anything-factortester-research/SKILL.md"
PACKAGED_SKILL = (
    ROOT
    / "tools/cli/agent-harness/cli_anything/factortester_research/skills/SKILL.md"
)


def pytest_sessionstart(session: pytest.Session) -> None:
    """Reject generated Skill drift before collecting unrelated tests."""
    if PACKAGED_SKILL.read_bytes() == CANONICAL_SKILL.read_bytes():
        return
    raise pytest.UsageError(
        "the packaged research Skill differs from its canonical source; "
        "merge intended changes into skills/cli-anything-factortester-research/"
        "SKILL.md, then run tools/cli/agent-harness/scripts/sync_skill.py --write"
    )
