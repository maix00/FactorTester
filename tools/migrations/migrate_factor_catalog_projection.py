"""Explicit backfill of source-free family and individual-factor read projections."""
from __future__ import annotations

import argparse
import json
import sqlite3

import settings as Settings


def migrate(*, apply: bool = False, principal: str = "") -> dict:
    with sqlite3.connect(f"file:{Settings.CACHE_DB_PATH}?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        sources = conn.execute("SELECT count(*) FROM factor_family_sources").fetchone()[0] if "factor_family_sources" in tables else 0
        configs = conn.execute("SELECT count(*) FROM account_domain_entities WHERE entity_type='factor_param_config'" +
            (" AND principal=?" if principal else ""), (principal,) if principal else ()).fetchone()[0] if "account_domain_entities" in tables else 0
    result = {"source_rows": sources, "configuration_rows": configs, "applied": False}
    if apply:
        from tools.data.sqlite.factor_metadata import sync_factor_metadata_sqlite_store
        from server.manager.storage.account_domain.local import LocalAccountDomainStore
        sync_factor_metadata_sqlite_store()
        local = LocalAccountDomainStore(Settings.CACHE_DB_PATH)
        local.rebuild_factor_catalog(principal)
        with sqlite3.connect(Settings.CACHE_DB_PATH) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("catalog backfill integrity check failed")
            result["factor_rows"] = conn.execute("SELECT count(*) FROM account_domain_entities WHERE entity_type='factor_catalog_entry'").fetchone()[0]
        result["applied"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--principal", default="")
    args = parser.parse_args()
    print(json.dumps(migrate(apply=args.apply, principal=args.principal), ensure_ascii=False))


if __name__ == "__main__":
    main()
