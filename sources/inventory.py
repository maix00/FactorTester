"""Read-only, paginated installed Bundle inventory. No plugin activation."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from traderesearch_data.bundles import discover_bundle_manifests


def inventory_report(root: Path, *, offset: int = 0, limit: int = 100) -> dict:
    if offset < 0 or not 1 <= limit <= 500:
        raise ValueError("invalid inventory page")
    bundles = discover_bundle_manifests(root)
    records = []
    digest = sha256()
    position = 0
    for bundle in sorted(bundles, key=lambda item: item.bundle_id):
        for member in sorted(bundle.members, key=lambda item: item.id):
            digest.update(json.dumps([bundle.bundle_id, member.id], separators=(",", ":")).encode() + b"\n")
            if offset <= position < offset + limit:
                records.append({"bundle_id": bundle.bundle_id, "member_id": member.id,
                                "kind": member.kind, "data_type": member.data_type,
                                "frequency": member.frequency, "provisioner": bundle.provisioner,
                                "execution_location": bundle.execution_location,
                                "update_policy": asdict(member.update_policy),
                                "runtime_status": "not_validated"})
            position += 1
    return {"schema_version": 1, "dry_run": True, "data_migration_performed": False,
            "bundle_count": len(bundles), "member_count": position,
            "product_binding_count": sum(len(bundle.product_bindings) for bundle in bundles),
            "member_ref_sha256": digest.hexdigest(),
            "offset": offset, "records": records,
            "next_offset": offset + limit if offset + limit < position else None,
            "runtime_validated": 0, "needs_runtime_validation": position}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    options = parser.parse_args()
    try:
        report = inventory_report(options.root, offset=options.offset, limit=options.limit)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Bundle inventory failed: {error}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
