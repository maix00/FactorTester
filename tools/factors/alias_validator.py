"""Fast batch generation and validation of canonical FactorFamily aliases."""

from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

from tools.factors.FactorFamily import FactorFamily


def canonicalize_factor_aliases(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Canonicalize a batch while loading each source family only once."""
    if not isinstance(requests, list) or not requests:
        raise ValueError("alias validation requests must be a non-empty list")
    results: list[dict[str, Any]] = []
    for index, request in enumerate(requests):
        if not isinstance(request, dict):
            raise ValueError(f"alias validation request {index} must be an object")
        source_file = str(request.get("source_file") or "")
        identity = str(request.get("identity") or "")
        object_kind = str(request.get("object_kind") or "")
        blob_hash = str(request.get("blob_hash") or "")
        if not source_file or not identity or not blob_hash:
            raise ValueError(
                f"alias validation request {index} is missing source identity"
            )
        canonical = canonical_factor_identity(
            source_file=Path(source_file),
            identity=identity,
            object_kind=object_kind,
            blob_hash=blob_hash,
        )
        results.append({
            "index": index,
            "identity": identity,
            "canonical_identity": canonical,
            "valid": identity == canonical,
        })
    return results


def canonical_factor_identity(
    *,
    source_file: Path,
    identity: str,
    object_kind: str,
    blob_hash: str,
) -> str:
    """Return the exact alias emitted by the selected committed family."""
    family_alias = identity.split("|", 1)[0]
    family = _load_factor_family(
        str(source_file.expanduser().resolve()), family_alias, blob_hash,
    )
    if object_kind == "factor-family":
        return str(family.alias)
    if object_kind != "factor":
        raise ValueError("factor object kind is invalid")
    parameters = family.parse_alias(identity)
    return family.get_alias(**parameters)


@lru_cache(maxsize=128)
def _load_factor_family(
    source_file: str,
    family_alias: str,
    blob_hash: str,
) -> FactorFamily:
    source_path = Path(source_file)
    digest = hashlib.sha256(
        f"{source_path}:{blob_hash}".encode("utf-8")
    ).hexdigest()[:20]
    module_name = f"_factor_workspace_identity_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load factor source: {source_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        candidates = [
            value for value in vars(module).values()
            if (
                isinstance(value, type)
                and issubclass(value, FactorFamily)
                and value is not FactorFamily
                and value.__module__ == module_name
            )
        ]
        for candidate in candidates:
            family = candidate()
            if str(family.alias) == family_alias:
                return family
    finally:
        sys.modules.pop(module_name, None)
    raise ValueError(
        f"Factor source does not define family {family_alias!r}: {source_path}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Batch-generate canonical aliases without loading the full CLI",
    )
    parser.add_argument(
        "--input", type=Path,
        help="JSON file containing a requests array; defaults to stdin",
    )
    arguments = parser.parse_args(argv)
    try:
        raw = (
            arguments.input.read_text(encoding="utf-8")
            if arguments.input is not None
            else sys.stdin.read()
        )
        payload = json.loads(raw)
        requests = payload.get("requests") if isinstance(payload, dict) else None
        results = canonicalize_factor_aliases(requests)
        output = {"schema_version": 1, "results": results}
        json.dump(output, sys.stdout, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")
        return 0 if all(item["valid"] for item in results) else 2
    except (OSError, ValueError, json.JSONDecodeError) as error:
        json.dump(
            {"schema_version": 1, "error": str(error)},
            sys.stdout, ensure_ascii=False, sort_keys=True,
        )
        sys.stdout.write("\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
