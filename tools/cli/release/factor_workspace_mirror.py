"""Client-safe lookup for the registered canonical factor workspace."""

from __future__ import annotations

from pathlib import Path

from .factor_worktree import CanonicalFactorRepoStore
from .locations import default_client_root


def existing_client_factor_workspace(
    username: str, *, client_root: Path | None = None,
) -> Path | None:
    """Return the registered canonical repository when it belongs to *username*.

    The packaged client must not import Manager-side ``tools.data`` storage.
    Its filesystem authority is the canonical repository registered in the
    versioned client root.  Missing or mismatched registration means that a
    remote write succeeds without creating an implicit local directory.
    """
    user = str(username or "").strip()
    if not user:
        return None
    try:
        settings = CanonicalFactorRepoStore(
            client_root or default_client_root(),
        ).load()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    owner = str(settings.get("owner_ref") or "").strip()
    owner_username = owner.split("@")[1] if owner.count("@") >= 2 else owner
    if user not in {owner, owner_username}:
        return None
    return Path(str(settings["path"])).expanduser().resolve()
