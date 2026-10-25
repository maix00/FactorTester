#!/usr/bin/env python3
"""Application-level smoke test for CouchDB authority mode."""

from __future__ import annotations

import argparse
import json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    args = parser.parse_args(argv)
    from tools.data.account_manage import load_product_groups
    from tools.data.sqlite.factor_metadata import list_factor_summaries
    from server.services.strategy_library.store import StrategyLibraryStore
    import settings as Settings

    groups = load_product_groups(args.owner)
    public = list_factor_summaries("public", None)
    custom = list_factor_summaries("custom", args.owner)
    strategy = StrategyLibraryStore(Settings.CACHE_DB_PATH)
    rows, total = strategy.list_visible_entries(
        principal=args.owner, scope="mine", subordinate_users=set(),
    )
    print(json.dumps({
        "product_groups": len(groups),
        "public_factors": len(public),
        "custom_factors": len(custom),
        "strategies": total,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
