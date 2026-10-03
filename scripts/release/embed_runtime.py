"""Refresh the client runtime only when the embedded revision is stale."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from scripts.release.assets import embed_client_runtime


REPO = Path(__file__).resolve().parents[2]
_REVISION = re.compile(r"^[0-9a-f]{40}$")


def ensure_client_runtime(
    *, app: Path, version: str, source_revision: str,
) -> bool:
    # Validate before the fast path.  A malformed receipt must never be
    # accepted merely because it happens to carry the same malformed value;
    # otherwise the later activation step fails with a much less actionable
    # error after packaging has already completed.
    if not _REVISION.fullmatch(source_revision):
        raise ValueError("runtime source revision must be a full 40-character Git revision")
    resources = app / "Contents" / "Resources" / "FactorTester"
    receipt_path = resources / "bundle-receipt.json"
    cli_path = resources / "bin" / "factortester"
    manager_cli_path = resources / "bin" / "factortester-manager"
    report_renderer_path = (
        resources / "bin" / "factortester-report-renderer"
    )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        receipt = {}
    if (
        receipt.get("source_revision") == source_revision
        and receipt.get("version") == version
        and cli_path.is_file()
        and manager_cli_path.is_file()
        and report_renderer_path.is_file()
    ):
        return False
    embed_client_runtime(
        REPO,
        app,
        version=version,
        source_revision=source_revision,
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()
    refreshed = ensure_client_runtime(**vars(args))
    print("refreshed" if refreshed else "reused")


if __name__ == "__main__":
    main()
