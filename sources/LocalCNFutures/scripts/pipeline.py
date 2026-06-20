"""Orchestrate LocalCNFutures offline generation and lightweight catalog sync."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from scripts.data_dir import CACHE_DB_PATH
from sources.LocalCNFutures import SOURCE_DATA_DIR
from sources.LocalCNFutures.product_catalog import (
    discover_products,
    load_product_catalog,
    sync_observed_trading_sessions,
    sync_product_catalog,
)
from sources.LocalCNFutures.artifacts import CONTINUOUS_KEY, TERM_STRUCTURE_KEY
from tools.data.artifacts import ArtifactCoordinator


def inspect_pipeline(
    *,
    data_dir: str | Path = SOURCE_DATA_DIR,
    db_path: str | Path = CACHE_DB_PATH,
) -> dict[str, Any]:
    root = Path(data_dir)
    discovered = discover_products(root)
    catalog = load_product_catalog(data_dir=root, db_path=db_path, sync=False) if Path(db_path).is_file() else None
    catalog_names = set(catalog["_product_name"].astype(str)) if catalog is not None else set()
    discovered_names = set(discovered["product_name"].astype(str))
    artifacts = ArtifactCoordinator(db_path=db_path).inspect_all()
    return {
        "discovered_count": len(discovered_names),
        "new_products": sorted(discovered_names - catalog_names),
        "has_min1_count": int(discovered["has_min1"].sum()) if not discovered.empty else 0,
        "has_day1_count": int(discovered["has_day1"].sum()) if not discovered.empty else 0,
        "artifacts": artifacts,
    }


def run_pipeline(
    *,
    data_dir: str | Path = SOURCE_DATA_DIR,
    db_path: str | Path = CACHE_DB_PATH,
    generate_main: bool = False,
    generate_term_structure: bool = False,
    force_sessions: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(data_dir)
    result = inspect_pipeline(data_dir=root, db_path=db_path)
    result.update({
        "dry_run": bool(dry_run),
        "generated_main": False,
        "generated_term_structure": False,
        "sessions_refreshed": False,
    })
    if dry_run:
        return result

    coordinator = ArtifactCoordinator(db_path=db_path)
    if generate_main:
        coordinator.ensure(CONTINUOUS_KEY, force=True)
        result["generated_main"] = True

    if generate_term_structure:
        coordinator.ensure(TERM_STRUCTURE_KEY, force=True)
        result["generated_term_structure"] = True

    sync_product_catalog(data_dir=root, db_path=db_path)
    if force_sessions or generate_main:
        observed = sync_observed_trading_sessions(
            data_dir=root,
            db_path=db_path,
            force=force_sessions,
        )
        result["sessions_refreshed"] = True
        result["observed_session_count"] = len(observed)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update LocalCNFutures derived data and catalog")
    parser.add_argument("--generate-main", action="store_true", help="Run heavy main-series generation")
    parser.add_argument("--generate-term-structure", action="store_true", help="Regenerate term structure")
    parser.add_argument("--force-sessions", action="store_true", help="Re-infer sessions for every MIN1 product")
    parser.add_argument("--dry-run", action="store_true", help="Inspect changes without writing")
    args = parser.parse_args(argv)
    print(run_pipeline(
        generate_main=args.generate_main,
        generate_term_structure=args.generate_term_structure,
        force_sessions=args.force_sessions,
        dry_run=args.dry_run,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
