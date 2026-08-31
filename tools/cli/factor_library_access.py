"""Authorization boundaries for factor-library mutation commands."""

from __future__ import annotations

import click

from tools.cli.agent_auth import load_capability


def require_user_factor_library_write() -> None:
    """Allow a signed-in user or its ``self`` Profile to mutate the user library."""
    capability = load_capability()
    if capability is not None and capability.profile_id != "self":
        raise click.ClickException(
            "只有用户本人或 self 研究身份可以修改用户因子库；"
            "其他研究身份只能在自己的 factor-worktree 中提交 Git 变更"
        )
