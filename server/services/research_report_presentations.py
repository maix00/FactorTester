"""Deterministic, bounded report labels for immutable research inputs."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson

_ANALYSIS_ZH = {
    "ic": "截面 IC",
    "backtest": "回测",
    "factor_evaluation": "因子评价",
    "factor_type_analysis": "因子类别分析",
}


def run_spec_presentation(
    run_spec: dict[str, Any],
    *,
    run_spec_hash: str,
    run_id: str = "",
    sample_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a readable chip plus the complete immutable RunSpec detail."""
    analyses = [
        _ANALYSIS_ZH.get(str(item), str(item))
        for item in run_spec.get("analyses") or []
    ]
    sample = sample_identity or {}
    start = str(sample.get("sample_start") or "")
    end = str(sample.get("sample_end") or "")
    factors = _factor_families(run_spec)
    session = _session_alias(run_spec)
    fee = _fee_alias(run_spec)
    parts = [
        " / ".join(analyses) or "研究运行",
        session,
        f"{start}—{end}" if start and end else "",
        "、".join(factors),
        fee,
    ]
    alias = " · ".join(item for item in parts if item)
    target_ref = f"run:{run_id}" if run_id else f"runspec:{run_spec_hash}"
    return {
        "schema_version": 1,
        "object_kind": "run_spec",
        "target_ref": target_ref,
        "alias_zh": alias[:240],
        "summary_zh": (
            f"{alias}；"
            + (
                "服务器接受后的冻结配置"
                if run_id else "运行前拟提交配置"
            )
            + f" r{int(run_spec.get('configuration_revision') or 0)}"
        )[:500],
        "run_spec_hash": run_spec_hash,
        "run_spec_version": int(run_spec.get("run_spec_version") or 0),
        "analysis_kinds": list(run_spec.get("analyses") or []),
        "sample_start": start,
        "sample_end": end,
        "factor_families": factors,
        "complete_parameters": run_spec,
        "complete_parameters_json": orjson.dumps(
            run_spec,
            option=orjson.OPT_INDENT_2,
        ).decode(),
        "strict_process_batch_candidate_key": strict_process_batch_candidate_key(
            run_spec,
            sample_identity=sample_identity,
        ),
    }


def trial_plan_presentation(plan: dict[str, Any]) -> dict[str, Any]:
    """Project a readable TrialPlan label without discarding its full body."""
    stages = list(
        ((plan.get("stage_policy") or {}).get("ordered_stage_ids") or [])
    )
    samples = list(plan.get("samples") or [])
    start_end = sorted({
        str(item.get("sample_ref") or "")
        for item in samples if isinstance(item, dict)
    })
    family = str(plan.get("trial_family") or "试验计划").split(":")[-1]
    alias = (
        f"{family} · {len(stages)} 个阶段 · {len(samples)} 个样本定义"
    )
    plan_hash = hashlib.sha256(orjson.dumps(
        plan, option=orjson.OPT_SORT_KEYS,
    )).hexdigest()
    return {
        "schema_version": 1,
        "object_kind": "trial_plan",
        "target_ref": f"trial-plan:sha256:{plan_hash}",
        "alias_zh": alias[:240],
        "summary_zh": (
            f"{alias}；顺序：{' → '.join(stages) if stages else '未声明'}"
        )[:500],
        "trial_plan_id": str(plan.get("trial_plan_id") or ""),
        "trial_plan_version": int(plan.get("version") or 0),
        "ordered_stage_ids": stages,
        "sample_refs": start_end,
        "complete_parameters": plan,
        "complete_parameters_json": orjson.dumps(
            plan,
            option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS,
        ).decode(),
    }


def strict_process_batch_candidate_key(
    run_spec: dict[str, Any],
    *,
    sample_identity: dict[str, Any] | None,
) -> str:
    """Return a conservative co-process candidate key, never a scheduler act.

    Equal dates are deliberately insufficient. A batch may only share one
    execution process when the analysis, engine-facing configuration,
    retention/step policy, sample identity, and factor revisions match.
    The current scheduler does not consume this key; JobAttempt identities
    remain separate even if a future worker co-processes compatible attempts.
    """
    configuration = run_spec.get("configuration") or {}
    shared = configuration.get("shared") or {}
    payload = {
        "analysis_kinds": sorted(run_spec.get("analyses") or []),
        "retention_mode": run_spec.get("retention_mode"),
        "step_mode": bool(run_spec.get("step_mode")),
        "sample_identity_hash": str(
            (sample_identity or {}).get("sample_hash") or ""
        ),
        "configuration": configuration,
        "factors": shared.get("factors") or [],
    }
    return hashlib.sha256(orjson.dumps(
        payload, option=orjson.OPT_SORT_KEYS,
    )).hexdigest()


def _factor_families(run_spec: dict[str, Any]) -> list[str]:
    shared = ((run_spec.get("configuration") or {}).get("shared") or {})
    result: list[str] = []
    for item in shared.get("factors") or []:
        if not isinstance(item, dict):
            continue
        identity = item.get("identity") or {}
        alias = str(identity.get("family_alias") or "")
        if alias and alias not in result:
            result.append(alias)
    for analysis in _selected_analysis_configs(run_spec):
        candidates = [
            *((analysis.get("factor_selections") or [])),
            *((analysis.get("factors") or [])),
        ]
        local = (analysis.get("execution") or {}).get("settings") or {}
        if local.get("factor"):
            candidates.append({"alias": local["factor"]})
        for item in candidates:
            if not isinstance(item, dict):
                continue
            alias = str(item.get("alias") or "").split("|", 1)[0]
            if alias and alias not in result:
                result.append(alias)
    return result[:8]


def _session_alias(run_spec: dict[str, Any]) -> str:
    labels: list[str] = []
    paths: list[str] = []
    for analysis in _selected_analysis_configs(run_spec):
        selection = analysis.get("product_path_selection")
        # product_path_selections is an option catalog and can contain both
        # day/night groups. Only the explicitly selected object is semantic.
        for item in [selection]:
            if not isinstance(item, dict):
                continue
            labels.extend(
                str(item.get(field) or "")
                for field in ("label", "name")
            )
            paths.extend(
                str(path) for path in item.get("paths") or []
            )
        groups = analysis.get("groups") or (
            (analysis.get("group_settings") or {}).get("groups") or []
        )
        labels.extend(
            str(item.get("name") or "")
            for item in groups if isinstance(item, dict)
        )
    # Prefer selected object names. Path taxonomy includes the parent segment
    # "日夜盘", which by itself must never classify a day cohort as night.
    if any("夜盘" in value for value in labels):
        return "夜盘"
    if any("日盘" in value for value in labels):
        return "日盘"
    if any("/夜盘" in value for value in paths):
        return "夜盘"
    if any("/日盘/" in value for value in paths):
        return "日盘"
    return ""


def _fee_alias(run_spec: dict[str, Any]) -> str:
    if "backtest" not in (run_spec.get("analyses") or []):
        return ""
    analysis = (
        ((run_spec.get("configuration") or {}).get("analyses") or {})
        .get("backtest") or {}
    )
    local = (analysis.get("execution") or {}).get("settings") or {}
    modes = [str(local.get("fee_mode") or "")]
    groups = analysis.get("groups") or (
        (analysis.get("group_settings") or {}).get("groups") or []
    )
    modes.extend(
        str(item.get("fee_mode") or "")
        for item in groups if isinstance(item, dict)
    )
    modes = [item for item in modes if item]
    if modes and set(modes) == {"zero"}:
        return "无手续费"
    if any(item in {"auto", "historical", "exchange"} for item in modes):
        return "历史/交易所手续费"
    return ""


def _selected_analysis_configs(
    run_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    analyses = ((run_spec.get("configuration") or {}).get("analyses") or {})
    return [
        analyses[kind]
        for kind in run_spec.get("analyses") or []
        if isinstance(analyses.get(kind), dict)
    ]
