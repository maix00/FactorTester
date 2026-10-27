"""Browser transport/KaTeX contracts for the single alpha formula composer."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED_JS = ROOT / "server" / "manager" / "web" / "catalog" / "factor-detail-shared.js"
PROBE_JS = ROOT / "tests" / "scripts" / "fixtures" / "factor_preview_latex_probe.js"

from server.modules.shared import factor_preview_latex as fpl  # noqa: E402


def test_resolved_formula_version_covers_operator_grouping_semantics():
    """Changing persisted LaTeX layout must invalidate old resolved formulas."""
    assert fpl.RESOLVED_MATH_EXPR_VERSION == 7


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
        {"factor": factor, "values": values,
         "rendered":fpl.preview_expression(factor,values),
         "flat":fpl.preview_expression(factor,values,include_nested_definitions=False)}
        for factor, values in zip(factor_objects, values_list)
    ]
    proc = subprocess.run(
        ["node", str(PROBE_JS), str(SHARED_JS)],
        input=json.dumps(payload), capture_output=True, text=True,
        cwd=str(ROOT), check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


def test_browser_renders_alpha_response_for_every_case():
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


def test_parameter_header_values_do_not_expand_nested_factor_definitions():
    cases = _cases()
    factors = [case[1] for case in cases]
    values = [case[2] for case in cases]
    results = _node_previews(factors, values)
    by_name = {name: result for (name, *_), result in zip(cases, results)}

    nested = by_name["nested single"]
    assert nested["localExpression"] != nested["expression"]
    assert r"\textcolor{red}{\mathrm{Child}}" in nested["localExpression"]
    assert r"\textcolor{blue}{\mathrm{Child}}" not in nested["localExpression"]
    assert r"\textcolor{blue}{\mathrm{Child}}_t :=" not in nested["localExpression"]

    scalar = by_name["scalar duration"]
    assert scalar["localExpression"] == scalar["expression"]


def test_parameter_values_round_trip():
    """The exported parameter_values helper mirrors the frontend map."""
    factor = _factor("Mom", r"\textcolor{red}{N}", [("N", "WindowParam", "20d")])
    assert fpl.parameter_values(factor) == {"N": "20d"}


def test_nested_output_assignment_preserves_alignment():
    child = _child('Nested', r'\begin{aligned}A_t &:= 1, \\ X_t &:= A_t.\end{aligned}', [])
    parent = _factor('Parent', r'X_t &:= \textcolor{red}{P}', [('P', 'FactorParam', child)])
    result = fpl.preview_expression(parent)
    assert r'\textcolor{blue}{\mathrm{Nested}}_t &:= A_t;' in result
    assert _node_previews([parent], [{}])[0]['expression'] == result


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
    assert r'\textcolor{red}{\$Rev}\cdot ' in template
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
            assert node["resolved_math_expr_version"] == fpl.RESOLVED_MATH_EXPR_VERSION
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
    assert r"\operatorname{Resample}_{\textcolor{red}{\$F}}\left(" not in result

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

    actual_frequency = _factor(
        "ActualFrequency",
        r"\operatorname{Resample}_{\textcolor{red}{10m}}\left(\mathrm{I1}_t\right)",
        [("$F", "FactorFrequencyParam", "10m"),
         ("$Rev", "ReverseSignalParam", "1")],
    )
    actual_result = _node_previews([actual_frequency], [{}])[0]["expression"]
    assert actual_result.startswith(r"\textcolor{red}{-}\operatorname{Resample}")
    assert actual_result == fpl.preview_expression(actual_frequency)

    class ReversedReturn(FactorFamily):
        @staticmethod
        def factor_expr():
            return (-ColumnRef(DataColumn.OPEN)).as_intermediate("Returned")

    reversed_family = ReversedReturn()
    assert r"\mathrm{Returned}_t &:=" in reversed_family.math_expr
    assert r"\left(\mathrm{Returned}_t\right)" in reversed_family.math_expr


def test_browser_only_transports_previews_and_ignores_stale_responses():
    code = r'''
const fs=require('fs');
global.window={};
global.document={createElement:()=>({children:[],handlers:{},append(...nodes){this.children.push(...nodes)},addEventListener(k,f){this.handlers[k]=f},replaceChildren(){}})};
eval(fs.readFileSync(process.argv[1],'utf8'));
const shared=window.FTFactorDetailShared;
const factor={math_expr:'TEMPLATE',factor_family_alias:'Race'};
let show='', calls=0, firstStarted, secondStarted, firstReply, secondReply;
const first=new Promise(resolve=>{firstStarted=resolve});
const second=new Promise(resolve=>{secondStarted=resolve});
const api=(path,options)=>new Promise(resolve=>{if(path!=="/api/factor-library/families/formula-preview"||JSON.parse(options.body).parameter_values.N!==calls+1)throw Error("invalid HTTP payload");calls++;if(calls===1){firstReply=resolve;firstStarted()}else{secondReply=resolve;secondStarted()}});
window.katex={};window.FTUI={renderMath:(_node,value)=>{show=value}};
(async()=>{
 const local=shared.localFormula({t:x=>x,api},factor,{N:1});
 const old=local.root.children[0].children[1].handlers.click();
 await first;
 const latest=local.update({N:2});
 await second;
 secondReply({success:true,latex:'NEW'});await latest;
 firstReply({success:true,latex:'OLD'});await old;
 if(show!=='NEW'||calls!==2)throw Error('stale response overwrote current preview');
 let requestCount=0,reply;
 const options={api:()=>{requestCount++;return new Promise(r=>{reply=r})}};
 const a=shared.previewExpression(factor,{N:99},options);
 const b=shared.previewExpression(factor,{N:99},options);
 reply({success:true,latex:'ONE'});
 if((await a)!=='ONE'||(await b)!=='ONE'||requestCount!==1)throw Error('in-flight request not shared');
 process.stdout.write('ok');
})().catch(error=>{console.error(error);process.exit(1)});
'''
    result=subprocess.run(['node','-e',code,str(SHARED_JS)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert result.stdout=='ok'
    source=SHARED_JS.read_text()
    assert 'function renderPreviewNode' not in source
    assert 'function latexValue' not in source
    assert 'function appendPreviewDefinition' not in source
