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
        formula_identity = factor_formula_identity(
            source_file=Path(source_file),
            identity=identity,
            object_kind=object_kind,
            blob_hash=blob_hash,
        )
        results.append({
            "index": index,
            "identity": identity,
            **formula_identity,
            "valid": identity == formula_identity["canonical_identity"],
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
    return factor_formula_identity(
        source_file=source_file,
        identity=identity,
        object_kind=object_kind,
        blob_hash=blob_hash,
    )["canonical_identity"]


def factor_formula_identity(
    *,
    source_file: Path,
    identity: str,
    object_kind: str,
    blob_hash: str,
) -> dict[str, Any]:
    family_alias = identity.split("|", 1)[0]
    family = _load_factor_family(
        str(source_file.expanduser().resolve()), family_alias, blob_hash,
    )
    if object_kind == "factor-family":
        return {
            "canonical_identity": str(family.alias),
            "family_formula_fingerprint": family.expr.semantic_fingerprint(),
            "self_formula_fingerprint": "",
        }
    if object_kind != "factor":
        raise ValueError("factor object kind is invalid")
    from server.modules.shared.factor_param_utils import (
        factor_param_value_display,
        normalize_factor_param_row,
    )
    parameters = normalize_factor_param_row(family, family.parse_alias(identity))
    factor = family.get_factor(**parameters)
    expression = getattr(factor, "_source_expr", None) or factor.expr
    return {
        "canonical_identity": str(factor.alias),
        "family_formula_fingerprint": family.expr.semantic_fingerprint(),
        "self_formula_fingerprint": expression.semantic_fingerprint(),
        "params": {
            parameter.alias: factor_param_value_display(
                parameter, parameters.get(parameter.alias),
            )
            for parameter in family.params
        },
    }


def describe_factor_family(request: dict[str, Any]) -> dict[str, Any]:
    """Return frontend metadata for one family loaded by the engine helper."""
    source_file, family_name, blob_hash = _family_request(request)
    family = _load_factor_family(source_file, family_name, blob_hash)
    from server.modules.shared.param_meta import serialize_param_meta

    return {
        "family": str(family.alias),
        "family_formula_fingerprint": family.expr.semantic_fingerprint(),
        "title_zh": str(getattr(family, "desc", "") or ""),
        "description": str(getattr(family, "description", "") or ""),
        "math_expr": str(getattr(family, "math_expr", "") or ""),
        "params": [serialize_param_meta(param) for param in family.params],
    }


def instantiate_factor_family(request: dict[str, Any]) -> dict[str, Any]:
    """Normalize selected parameters and emit one canonical factor alias."""
    source_file, family_name, blob_hash = _family_request(request)
    params = request.get("params")
    if not isinstance(params, dict):
        raise ValueError("factor params must be an object")
    family = _load_factor_family(source_file, family_name, blob_hash)
    from server.modules.shared.factor_param_utils import (
        factor_param_value_display,
        normalize_factor_param_row,
    )

    normalized = normalize_factor_param_row(family, params)
    factor = family.get_factor(**normalized)
    expression = getattr(factor, "_source_expr", None) or factor.expr
    return {
        "family": str(family.alias),
        "alias": str(factor.alias),
        "family_formula_fingerprint": family.expr.semantic_fingerprint(),
        "self_formula_fingerprint": expression.semantic_fingerprint(),
        "params": {
            parameter.alias: factor_param_value_display(
                parameter, normalized.get(parameter.alias),
            )
            for parameter in family.params
        },
    }


def _family_request(request: dict[str, Any]) -> tuple[str, str, str]:
    if not isinstance(request, dict):
        raise ValueError("factor engine request must be an object")
    source_file = str(request.get("source_file") or "")
    family = str(request.get("family") or "")
    blob_hash = str(request.get("blob_hash") or "")
    if not source_file or not family or not blob_hash:
        raise ValueError("factor engine request is missing source identity")
    return source_file, family, blob_hash


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
        operation = payload.get("operation") if isinstance(payload, dict) else None
        if operation is None:
            requests = payload.get("requests") if isinstance(payload, dict) else None
            results = canonicalize_factor_aliases(requests)
            output = {"schema_version": 1, "results": results}
            exit_code = 0 if all(item["valid"] for item in results) else 2
        elif operation == "describe":
            output = {
                "schema_version": 1,
                "result": describe_factor_family(payload.get("request")),
            }
            exit_code = 0
        elif operation == "instantiate":
            output = {
                "schema_version": 1,
                "result": instantiate_factor_family(payload.get("request")),
            }
            exit_code = 0
        else:
            raise ValueError("factor engine operation is invalid")
        json.dump(output, sys.stdout, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")
        return exit_code
    except (OSError, ValueError, json.JSONDecodeError) as error:
        json.dump(
            {"schema_version": 1, "error": str(error)},
            sys.stdout, ensure_ascii=False, sort_keys=True,
        )
        sys.stdout.write("\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
