"""Authoritative local locations for release-signing material."""

from __future__ import annotations

from pathlib import Path


def manifest_private_key(
    channel: str,
    supplied: Path | None,
    *,
    home: Path | None = None,
) -> Path:
    """Resolve an explicit key or the one stable Beta publisher key.

    Main publishing intentionally remains explicit because its authority may
    move to a different publisher.  Beta uses the long-lived server release
    identity stored in the user's FactorTester application support directory.
    """
    if supplied is not None:
        return supplied
    if channel != "beta":
        raise ValueError("Main release manifest private key must be specified")
    root = home if home is not None else Path.home()
    candidate = (
        root
        / "Library/Application Support/FactorTester"
        / "server-release-signing/beta-private.pem"
    )
    if not candidate.is_file():
        raise ValueError(
            "Beta release manifest private key is not installed in the "
            "FactorTester application support directory"
        )
    return candidate
