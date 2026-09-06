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


def test_signal_alignment_intermediates_and_reverse_match_real_metadata():
    from types import SimpleNamespace
    from tools.factors import FactorFamily
    from tools.factors.FactorExpr import ColumnRef, SignalAlign
    from tools.data.types import DataColumn
    from server.modules.shared.factor_instance_metadata import build_factor_instance_metadata
    from server.services.run_input_inspection import family_template_latex

    root = ColumnRef(DataColumn.CLOSE).as_intermediate()
    family = FactorFamily(alias="LatexSignalAlignmentProbe", expr=root)
    template = family.math_expr
    assert template == family_template_latex(family)
    assert r"\operatorname{Resample}_{\textcolor{red}{\$F}}" in template
    assert r"\mathrm{I1}_t &:=" in template
    assert r"\left(\mathrm{I1}_t\right)" in template
    assert r"\textcolor{red}{5m}" in SignalAlign(root, "5m").to_latex()
    cases = []
    for frequency in ["", "5m", "1d"]:
        for reverse in [False, True, "0", "1", "-1", "reverse"]:
            node = build_factor_instance_metadata(
                family, SimpleNamespace(alias="Probe"), {"$F": frequency, "$Rev": reverse},
            )
            assert node["math_expr"] == template
            cases.append(node)
    for node, result in zip(cases, _node_previews(cases, [{}] * len(cases))):
        assert node["resolved_math_expr"] == result["expression"]
        values = fpl.parameter_values(node)
        assert (r"\textcolor{red}{-}" in result["expression"]) == (
            str(values["$Rev"]).lower() in {"true", "1", "-1", "reverse"}
        )
        assert (r"\$F" in result["expression"]) == (values.get("$F", "") == "")

    leaf = _factor("Leaf", template, [("$F", "FactorFrequencyParam", "1m"),
                                    ("$Rev", "ReverseSignalParam", True)])
    middle = _factor("Middle", template.replace("C_t", r"\textcolor{red}{P}"),
                     [("$F", "FactorFrequencyParam", "5m"),
                      ("$Rev", "ReverseSignalParam", False),
                      ("P", "FactorParam", leaf, leaf)])
    outer = _factor("Outer", r"\operatorname{Resample}_{\textcolor{red}{\$F}}\left(\textcolor{red}{P}\right)",
                    [("$F", "FactorFrequencyParam", "1d"),
                     ("$Rev", "ReverseSignalParam", True),
                     ("P", "FactorParam", middle, middle)])
    result = _node_previews([outer], [{}])[0]["expression"]
    assert result == fpl.preview_expression(outer)
    assert result.count(r"\operatorname{Resample}") == 3
    assert result.count(r"\textcolor{red}{-}") == 2

    # A signal operand may itself contain line breaks (e.g. BarSearch).
    # Reversal belongs outside Resample, never inside that inner alignment.
    complex_node = _factor("Search",
        r"\operatorname{Resample}_{\textcolor{red}{\$F}}\left("
        r"\left\{k\middle|\begin{aligned}X_t&:=C_t\\X_t-X_{t-k}&>0\end{aligned}\right\}"
        r"\right)", [("$F", "FactorFrequencyParam", ""),
                      ("$Rev", "ReverseSignalParam", False)])
    overrides = {"$F": "30m", "$Rev": True}
    result = _node_previews([complex_node], [overrides])[0]["expression"]
    assert result == fpl.preview_expression(complex_node, overrides)
    assert result.startswith(r"\textcolor{red}{-}\operatorname{Resample}")

    class ReversedReturn(FactorFamily):
        @staticmethod
        def factor_expr():
            return (-ColumnRef(DataColumn.OPEN)).as_intermediate("Returned")

    reversed_family = ReversedReturn()
    assert r"\mathrm{Returned}_t &:=" in reversed_family.math_expr
    assert r"\left(\mathrm{Returned}_t\right)" in reversed_family.math_expr
