"""Dry-run or apply an exact report-placeholder replacement manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.cli.release.research_reporting.placeholder_apply import (
    migrate_package,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--branch-id", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--product-group", required=True)
    parser.add_argument("--current-node", required=True)
    parser.add_argument("--client-root", type=Path, required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    replacements = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(replacements, list):
        raise ValueError("placeholder manifest must be an array")
    result = migrate_package(
        package_root=args.package_root,
        branch_id=args.branch_id,
        replacements=replacements,
        product_group=args.product_group,
        current_node=args.current_node,
        apply=args.apply,
        client_root=args.client_root,
        profile_id=args.profile_id,
        agent_id=args.agent_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
