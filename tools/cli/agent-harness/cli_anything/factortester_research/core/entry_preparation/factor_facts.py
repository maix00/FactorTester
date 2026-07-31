"""Source-free factor facts derived from the public ``describe`` response."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


_NODE_PARAM_KEYS = {
    "alias", "type", "default_value", "value", "intermediate_name",
}
_BINARY_LATEX = {
    "+": "+",
    "-": "-",
    "*": r"\cdot",
    "/": "/",
    "**": "^",
}


def compact_factor_facts(
    describe: dict[str, Any],
    *,
    factor_ref: str,
) -> dict[str, Any]:
    """Project one describe payload into bounded auditable expression facts."""
    if not isinstance(describe, dict):
        raise ValueError("factor describe response must be an object")
    factor = describe.get("factor")
    if not isinstance(factor, dict):
        raise ValueError("factor describe response is missing factor metadata")
    graph = describe.get("debug_graph")
    if not isinstance(graph, dict):
        raise ValueError(
            "factor describe response needs --debug-graph for AST facts"
        )
    ast = _compact_ast(graph)
    params = [
        {
            key: item.get(key)
            for key in ("alias", "type", "default_value")
        }
        for item in factor.get("params") or []
        if isinstance(item, dict)
    ]
    columns = _text_list(describe.get("column_refs"), "column_refs")
    operators = _text_list(describe.get("operator_keys"), "operator_keys")
    identity = {
        "factor_ref": str(factor_ref),
        "factor": {
            "id": str(factor.get("id") or ""),
            "name": str(factor.get("name") or factor_ref),
            "source": str(factor.get("source") or ""),
            "owner_username": str(factor.get("owner_username") or ""),
            "source_access": bool(factor.get("source_access")),
            "chinese_name": str(factor.get("chinese_name") or ""),
            "description": str(factor.get("description") or ""),
            "params": params,
        },
        "ast": ast,
        "column_refs": columns,
        "operator_keys": operators,
    }
    digest = hashlib.sha256(_canonical_bytes(identity)).hexdigest()
    expression_ref = f"factor-expression:sha256:{digest}"
    return {
        **identity,
        "latex": _latex_from_ast(ast),
        "expression_ref": expression_ref,
        "fact_refs": [
            expression_ref,
            *[
                f"data-column:{_safe_ref(factor_ref)}:{column}"
                for column in columns
            ],
        ],
    }


def _compact_ast(graph: dict[str, Any]) -> dict[str, Any]:
    raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("factor debug graph nodes must be a non-empty array")
    nodes = []
    ids = set()
    for item in raw_nodes:
        if not isinstance(item, dict) or type(item.get("id")) is not int:
            raise ValueError("factor debug graph node is invalid")
        node_id = item["id"]
        if node_id in ids:
            raise ValueError("factor debug graph node IDs must be unique")
        ids.add(node_id)
        inputs = item.get("inputs") or []
        if not isinstance(inputs, list) or not all(
            type(value) is int for value in inputs
        ):
            raise ValueError("factor debug graph inputs must be integer IDs")
        raw_params = item.get("params") or {}
        if not isinstance(raw_params, dict):
            raise ValueError("factor debug graph params must be an object")
        nodes.append({
            "id": node_id,
            "key": str(item.get("key") or ""),
            "cat": str(item.get("cat") or ""),
            "label": str(item.get("label") or ""),
            "inputs": list(inputs),
            "params": {
                key: raw_params[key]
                for key in sorted(set(raw_params) & _NODE_PARAM_KEYS)
            },
        })
    root_id = graph.get("root_id")
    if type(root_id) is not int or root_id not in ids:
        raise ValueError("factor debug graph root_id is invalid")
    referenced = {
        input_id for node in nodes for input_id in node["inputs"]
    }
    if not referenced.issubset(ids):
        raise ValueError("factor debug graph references unknown inputs")
    return {"root_id": root_id, "nodes": sorted(nodes, key=lambda n: n["id"])}


def _latex_from_ast(ast: dict[str, Any]) -> str:
    by_id = {item["id"]: item for item in ast["nodes"]}
    active: set[int] = set()
    rendered: dict[int, str] = {}

    def emit(node_id: int) -> str:
        if node_id in rendered:
            return rendered[node_id]
        if node_id in active:
            raise ValueError("factor debug graph contains a cycle")
        active.add(node_id)
        node = by_id[node_id]
        children = [emit(value) for value in node["inputs"]]
        result = _node_latex(node, children)
        active.remove(node_id)
        rendered[node_id] = result
        return result

    return emit(ast["root_id"])


def _node_latex(node: dict[str, Any], children: list[str]) -> str:
    key = node["key"]
    params = node["params"]
    if key == "Return":
        return _arity(key, children, 1)[0]
    if key == "Constant":
        return _latex_atom(params.get("value", node["label"]))
    if node["cat"] == "leaf":
        alias = str(params.get("alias") or node["label"] or key)
        if params.get("type") == "DataColumnParam":
            return rf"\mathrm{{{_escape_latex(alias)}}}"
        return _escape_latex(alias)
    if key in {"+", "-", "*"}:
        left, right = _arity(key, children, 2)
        return f"{_parenthesize(left)} {_BINARY_LATEX[key]} {_parenthesize(right)}"
    if key == "/":
        numerator, denominator = _arity(key, children, 2)
        return rf"\frac{{{numerator}}}{{{denominator}}}"
    if key == "**":
        base, exponent = _arity(key, children, 2)
        return rf"{{{base}}}^{{{exponent}}}"
    operator = key.replace("\\", r"\backslash ").replace("_", r"\_")
    return (
        rf"\operatorname{{{operator}}}"
        rf"\left({','.join(children)}\right)"
    )


def _arity(key: str, children: list[str], count: int) -> list[str]:
    if len(children) != count:
        raise ValueError(f"factor AST operator {key} needs {count} inputs")
    return children


def _parenthesize(value: str) -> str:
    if value.startswith(r"\frac") or " + " in value or " - " in value:
        return rf"\left({value}\right)"
    return value


def _latex_atom(value: Any) -> str:
    text = str(value)
    if re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?", text, re.I):
        return text
    return rf"\mathrm{{{_escape_latex(text)}}}"


def _escape_latex(value: str) -> str:
    return (
        value.replace("\\", r"\backslash ")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("%", r"\%")
        .replace("#", r"\#")
        .replace("&", r"\&")
        .replace("$", r"\$")
        .replace("_", r"\_")
    )


def _text_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"factor describe {field} must be a text array")
    return list(dict.fromkeys(value))


def _safe_ref(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "factor"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
