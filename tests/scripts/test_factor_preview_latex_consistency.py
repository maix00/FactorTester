"""Cross-end consistency: backend preview LaTeX must equal the frontend.

The browser composes the factor preview LaTeX in
``server/manager/web/catalog/factor-detail-shared.js`` (``previewExpression``).
This test proves the backend port in
``server/modules/shared/factor_preview_latex.py`` produces the byte-identical
string for the same factor object, by running both implementations and
asserting equality.

The frontend is executed in ``node`` with a minimal ``window`` stub so the IIFE
can install ``window.FTFactorDetailShared``; ``previewExpression`` is then
called on the same factor objects the backend port receives.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED_JS = ROOT / "server" / "manager" / "web" / "catalog" / "factor-detail-shared.js"
PROBE_JS = ROOT / "tests" / "scripts" / "fixtures" / "factor_preview_latex_probe.js"

from server.modules.shared import factor_preview_latex as fpl  # noqa: E402


def _rows(params):
    rows = []
    for p in params:
        if isinstance(p, dict):
            rows.append(p)
            continue
        row = {"alias": p[0], "type": p[1], "value": p[2]}
        if len(p) > 3:
            row["nested_factor"] = p[3]
        rows.append(row)
    return rows


def _factor(alias, template, params, **extra):
    return {
        "factor_family_alias": alias,
        "math_expr": template,
        "parameter_definitions": _rows(params),
        "factor_alias": f"{alias}|test",
        **extra,
    }


def _child(alias, template, params, **extra):
    return _factor(alias, template, params, **extra)


# --- Scenarios ---------------------------------------------------------------
def _cases():
    cases = []

    # 1. no nesting, scalar duration parameter
    cases.append(("scalar duration", _factor("Mom", r"\mathrm{Close}_t \cdot \textcolor{red}{N}",
        [("N", "WindowParam", "20d")]), {"N": "20d"}))

    # 2. DataColumn object value -> previewScalarValue pulls ".value"
    cases.append(("DataColumn object", _factor("Mom", r"\textcolor{red}{H} \times \textcolor{red}{N}",
        [("H", "DataColumnParam", {"value": "HIGH"}),
         ("N", "WindowParam", {"value": "5d"})]),
        {"H": {"value": "HIGH"}, "N": {"value": "5d"}}))

    # 3. nested factor, single level, child is its own simple expression
    child_c = _child("Child", r"\mathrm{Child}_t := \textcolor{red}{K}", [("K", "WindowParam", "3d")])
    cases.append(("nested single", _factor("Mom", r"\textcolor{red}{C} + \mathrm{Base}_t",
        [("C", "FactorParam", child_c["factor_alias"], child_c)]), {}))

    # 4. nested child whose math_expr is an aligned multi-line env
    child_d = _child("ChildD",
        r"\begin{aligned}" + "\n" + r"A_t &:= \mathrm{High}_t \\" + "\n"
        + r"B_t &:= A_t - \textcolor{red}{K};" + "\n" + r"\end{aligned}",
        [("K", "WindowParam", "2d")])
    cases.append(("nested multiline aligned child",
        _factor("MomD", r"\textcolor{red}{C}", [("C", "FactorParam", child_d["factor_alias"], child_d)]), {}))

    # 5. two-level nesting (grandchild under a mid family param)
    grandchild = _child("Grand", r"\mathrm{Grand}_t := \textcolor{red}{G}", [("G", "WindowParam", "1d")])
    mid = _child("Mid", r"\textcolor{red}{G2} + \mathrm{Grand}_t",
        [("G2", "WindowParam", "2d"), ("Grand", "FactorParam", grandchild["factor_alias"], grandchild)])
    cases.append(("two-level", _factor("RootE", r"\textcolor{red}{Mid}",
        [("Mid", "FactorParam", mid["factor_alias"], mid)]), {}))

    # 6. child line already carries an alignment '&' (intermediate definition)
    child_f = _child("ChildF", r"A_t &:= X_t \\" + "\n" + r"B_t &:= A_t,",
        [("K", "WindowParam", "1d")])
    cases.append(("child with &", _factor("RootF", r"\textcolor{red}{C} + \mathrm{Base}_t",
        [("C", "FactorParam", child_f["factor_alias"], child_f)]), {}))

    # 7. multiple parameters: scalar + nested child
    child_g = _child("ChildG", r"X_t := \textcolor{red}{L}", [("L", "WindowParam", "4d")])
    cases.append(("multi params", _factor("RootG", r"\textcolor{red}{N} + \textcolor{red}{Ch}",
        [("N", "WindowParam", "10d"), ("Ch", "FactorParam", child_g["factor_alias"], child_g)]),
        {"N": "10d"}))

    # 8. no parameters -> no lines -> body returned as-is
    cases.append(("body only", _factor("Pure", r"\mathrm{Close}_t", []), {}))

    # 9. root template already wrapped in \begin{aligned}, no nested
    cases.append(("wrapped root no nested",
        _factor("Mom", r"\begin{aligned}" + "\n" + r"A_t &:= \mathrm{Close}_t \\" + "\n" + r"B_t &:= A_t" + "\n" + r"\end{aligned}",
            [("N", "WindowParam", "20d")]), {}))

    # 10. wrapped root template + nested param
    child_j = _child("CJ", r"\mathrm{Child}_t := \textcolor{red}{K}", [("K", "WindowParam", "3d")])
    cases.append(("wrapped root + nested",
        _factor("Rj", r"\begin{aligned}" + "\n" + r"A_t &:= \textcolor{red}{C} + \mathrm{Base}_t" + "\n" + r"\end{aligned}",
            [("C", "FactorParam", child_j["factor_alias"], child_j)]), {}))

    # 11. empty value with default_value fallback
    cases.append(("default_value",
        _factor("Rk", r"\textcolor{red}{N}",
            [{"alias": "N", "type": "WindowParam", "value": "", "default_value": "7d"}]), {}))

    # 12. family-draft nested factor (__factor_family_draft carries family + values)
    draft_child = {"__factor_family_draft": True,
        "__factor_family": _child("Draft", r"D_t := \textcolor{red}{D}", [("D", "WindowParam", "2d")]),
        "parameter_values": {"D": "2d"}}
    cases.append(("family draft nested",
        _factor("Rl", r"\textcolor{red}{C}", [("C", "FactorParam", "draft", draft_child)]), {}))

    # 13. compact params dict (parameter_rows object branch) instead of array
    cases.append(("compact params object",
        {"factor_family_alias": "Cp", "math_expr": r"\textcolor{red}{N}", "factor_alias": "Cp|t",
         "params": {"N": {"type": "WindowParam", "value": "15d"}}}, {}))

    return cases


def _node_previews(factor_objects, values_list):
    payload = [
        {"factor": factor, "values": values}
        for factor, values in zip(factor_objects, values_list)
    ]
    proc = subprocess.run(
        ["node", str(PROBE_JS), str(SHARED_JS)],
        input=json.dumps(payload), capture_output=True, text=True,
        cwd=str(ROOT), check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


def test_backend_preview_matches_frontend_for_every_case():
    cases = _cases()
    factors = [c[1] for c in cases]
    values = [c[2] for c in cases]
    node_results = _node_previews(factors, values)
    assert len(node_results) == len(cases), (
        f"node returned {len(node_results)} results for {len(cases)} cases"
    )
    for idx, (name, factor, value_map) in enumerate(cases):
        python_expr = fpl.preview_expression(factor, value_map)
        js_expr = node_results[idx]["expression"]
        assert python_expr == js_expr, (
            f"backend/frontend preview mismatch for case '{name}' "
            f"(python={python_expr!r} js={js_expr!r})"
        )
        # every case must actually produce some composed output
        assert python_expr.strip(), f"case '{name}' produced an empty preview"


def test_parameter_values_round_trip():
    """The exported parameter_values helper mirrors the frontend map."""
    factor = _factor("Mom", r"\textcolor{red}{N}", [("N", "WindowParam", "20d")])
    assert fpl.parameter_values(factor) == {"N": "20d"}
