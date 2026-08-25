"""Research workspace, configuration, template, run, and job commands."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any

import click

from tools.cli.commands.research_report_common import scope_options
from tools.cli.commands.research_report_job_binding import freeze_report_binding
from tools.cli.commands.research_report_scope import resolve_branch_report_scope
from tools.cli.core.context import client_from_config, requested_ports
from tools.cli.core.errors import friendly_errors
from tools.cli.core.run_input_dependencies import (
    load as load_run_input_dependencies,
)
from tools.cli.core.run_input_dependencies import (
    option as run_input_option,
)
from tools.cli.core.strategy_spec import load_spec
from tools.cli.release.artifact_paths import artifact_destination
from tools.cli.release.job_cache import job_cache_directory
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.profile_factor_set_queries import profile_factor_context
from tools.cli.release.research_reporting.job_artifacts import collect_job_report
from tools.cli.release.research_reporting.references.factor_set_workspace import (
    validate_factor_set_reference,
)
from tools.cli.state import load_state, save_state
from tools.cli.step import field_occurrences, render_step_event


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _require_workspace():
    state = load_state()
    if not state.workspace_id:
        raise click.ClickException("尚未选择 research workspace；请先运行 factortester workspace create/use")
    return state


def _load_profile_factor_sources(root: Path | None) -> list[dict[str, str]]:
    """Read only custom factor files from an Agent-owned Profile worktree."""
    if root is None:
        return []
    # Keep the HTTP-only CLI startup independent from the server's full data
    # layer.  The storage validator is needed only when this optional local
    # source upload is explicitly requested.
    storage = importlib.import_module(
        "tools.data.factor_workspace.storage"
    )

    target = root.expanduser().resolve()
    if not storage.is_profile_factor_worktree_root(target):
        raise click.ClickException(
            "--profile-factor-worktree 必须指向 Profile 的 factor-worktree，"
            "不能上传 canonical 因子库"
        )
    source_dir = target / "custom_factors"
    if not source_dir.is_dir():
        raise click.ClickException(f"Profile 因子目录不存在: {source_dir}")
    sources: list[dict[str, str]] = []
    for path in sorted(source_dir.glob("*.py")):
        resolved = path.resolve()
        if resolved.parent != source_dir.resolve() or not resolved.is_file():
            continue
        sources.append({
            "path": f"custom_factors/{path.name}",
            "source_code": resolved.read_text(encoding="utf-8"),
        })
    if not sources:
        raise click.ClickException("Profile worktree 没有可上传的 custom_factors/*.py")
    return sources


def _load_factor_set_descriptors(
    target_refs: tuple[str, ...],
    *,
    release_profile: Path | None,
) -> list[dict[str, Any]]:
    if not target_refs:
        return []
    client_root = load_profile_root(release_profile)
    store = LocalProfileStore(client_root)
    values = []
    for target_ref in target_refs:
        matches = []
        for profile in store.list():
            try:
                _repository, roots = profile_factor_context(profile)
                matches.append(validate_factor_set_reference(
                    kind="factor", target_ref=target_ref, roots=roots,
                ))
            except (OSError, ValueError):
                continue
        if len(matches) != 1:
            raise click.ClickException(
                "--factor-set-ref 必须精确匹配一个已登记工作区中的 v2 因子集合"
            )
        value = matches[0]
        values.append({
            "target_ref": target_ref,
            "manifest": value["descriptor"],
        })
    return values


def _load_strategy_bundle(root: Path | None) -> list[dict[str, str]]:
    """Upload only actor source files from a Profile strategy worktree."""
    if root is None:
        return []
    target = root.expanduser().resolve()
    manifest = target / ".strategy_workspace" / "manifest.json"
    source_dir = target / "strategies"
    if not manifest.is_file() or not source_dir.is_dir():
        raise click.ClickException(
            "--profile-strategy-worktree 必须指向带 .strategy_workspace/manifest.json 的 Profile strategy-worktree"
        )
    sources: list[dict[str, str]] = []
    for path in sorted(source_dir.rglob("*.py")):
        if not path.is_file() or ".." in path.relative_to(target).parts:
            continue
        sources.append({
            "path": path.relative_to(target).as_posix(),
            "source_code": path.read_text(encoding="utf-8"),
        })
    if not sources:
        raise click.ClickException("Profile strategy-worktree 没有可上传的 strategies/*.py")
    return sources


def _load_strategy_specs(paths: tuple[Path, ...]) -> list[dict[str, Any]]:
    values = []
    for path in paths:
        try:
            values.append(load_spec(path).normalized())
        except ValueError as exc:
            raise click.ClickException(f"strategy spec 无效: {path}: {exc}") from exc
    return values


@click.group("workspace")
def workspace() -> None:
    """Manage durable research contexts and their active configuration."""


@click.group("external-factor")
def external_factor() -> None:
    """Validate and attach external precomputed factor artifacts."""


@external_factor.command("validate")
@click.argument(
    "manifest_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--attach",
    is_flag=True,
    help="Attach the validated immutable descriptor to the active workspace.",
)
@friendly_errors
def external_factor_validate(manifest_path: Path, attach: bool) -> None:
    client = client_from_config()
    artifact = client.validate_external_factor_artifact(str(manifest_path.resolve()))
    if attach:
        state = _require_workspace()
        configuration = client.get_workspace_configuration(state.workspace_id)
        payload = dict(configuration["payload"])
        shared = dict(payload["shared"])
        artifacts = [
            item for item in shared.get("external_factor_artifacts") or []
            if item.get("artifact_id") != artifact.get("artifact_id")
        ]
        artifacts.append(artifact)
        shared["external_factor_artifacts"] = artifacts
        payload["shared"] = shared
        value = client.update_workspace_configuration(
            state.workspace_id,
            expected_revision=state.configuration_revision,
            payload=payload,
        )
        state.configuration_revision = int(value["revision"])
        save_state(state)
    click.echo(_json({
        "artifact": artifact,
        "attached": attach,
        "workspace_id": load_state().workspace_id if attach else "",
    }))


@workspace.command("create")
@click.option("--factor-family", "factor_families", multiple=True, help="因子家族 alias，可重复。")
@click.option(
    "--factor", "factors", multiple=True,
    help="具体 factor，格式 FAMILY_ALIAS=FACTOR_ALIAS，可重复。",
)
@click.option("--title", default="Factor research", show_default=True)
@friendly_errors
def workspace_create(
    factor_families: tuple[str, ...], factors: tuple[str, ...], title: str,
) -> None:
    families = [{"alias": value} for value in factor_families]
    family_aliases = {item["alias"] for item in families}
    factor_rows = []
    for raw in factors:
        if "=" not in raw:
            raise click.ClickException("--factor 格式必须为 FAMILY_ALIAS=FACTOR_ALIAS")
        family_alias, factor_alias = raw.split("=", 1)
        family_alias = family_alias.strip()
        factor_alias = factor_alias.strip()
        if not family_alias or not factor_alias:
            raise click.ClickException("--factor 格式必须为 FAMILY_ALIAS=FACTOR_ALIAS")
        if family_alias not in family_aliases:
            families.append({"alias": family_alias})
            family_aliases.add(family_alias)
        factor_rows.append({"factor_family_alias": family_alias, "alias": factor_alias})
    value = client_from_config().create_workspace(
        factor_families=families,
        factors=factor_rows,
        title=title,
    )
    state = load_state()
    state.workspace_id = str(value["workspace_id"])
    state.configuration_revision = int(value["configuration"]["revision"])
    save_state(state)
    click.echo(
        f"workspace_id={state.workspace_id} "
        f"configuration_revision={state.configuration_revision}"
    )


@workspace.command("list")
@friendly_errors
def workspace_list() -> None:
    for item in client_from_config().list_workspaces():
        config = item.get("configuration") or {}
        click.echo(
            f"{item.get('workspace_id')} config_revision={config.get('revision')} "
            f"title={item.get('title') or '-'}"
        )


@workspace.command("use")
@click.argument("workspace_id")
@friendly_errors
def workspace_use(workspace_id: str) -> None:
    value = client_from_config().get_workspace(workspace_id)
    state = load_state()
    state.workspace_id = workspace_id
    state.configuration_revision = int((value.get("configuration") or {})["revision"])
    save_state(state)
    click.echo(
        f"workspace_id={workspace_id} "
        f"configuration_revision={state.configuration_revision}"
    )


@workspace.command("show")
@friendly_errors
def workspace_show() -> None:
    state = _require_workspace()
    click.echo(_json(client_from_config().get_workspace(state.workspace_id)))


@workspace.command("update")
@click.option("--file", "configuration_file", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@friendly_errors
def workspace_update(configuration_file: Path) -> None:
    state = _require_workspace()
    payload = json.loads(configuration_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise click.ClickException("configuration JSON must be an object")
    value = client_from_config().update_workspace_configuration(
        state.workspace_id,
        expected_revision=state.configuration_revision,
        payload=payload,
    )
    state.configuration_revision = int(value["revision"])
    save_state(state)
    click.echo(
        f"workspace_id={state.workspace_id} "
        f"configuration_revision={state.configuration_revision}"
    )


@workspace.command("ic-horizons")
@click.option(
    "--sampling", type=click.Choice(["explicit", "scale_aware"]),
    default="explicit", show_default=True,
    help="horizon 网格模式；scale_aware 按因子 $F 自动生成高频/日频/长尾采样点。",
)
@click.option(
    "--base", "bases", multiple=True,
    help="前瞻收益期基准；用 signal 跟随因子 $F，也可指定 1m、1d 等。可重复。",
)
@click.option(
    "--multiple", "multipliers", multiple=True, type=click.IntRange(min=1),
    help="每个基准展开的正整数倍数；可重复。",
)
@click.option(
    "--entry-delay-bar", "entry_delay_bars", multiple=True, type=click.IntRange(min=0),
    help="另行测试的入场延迟（以信号 bar 计）；不是持有期。可重复。",
)
@friendly_errors
def workspace_ic_horizons(
    sampling: str, bases: tuple[str, ...], multipliers: tuple[int, ...], entry_delay_bars: tuple[int, ...],
) -> None:
    """Set explicit IC forward-return horizons on the active workspace.

    Example: ``workspace ic-horizons --base signal --base 1m --multiple 1
    --multiple 5 --entry-delay-bar 0 --entry-delay-bar 1``.
    """
    state = _require_workspace()
    client = client_from_config()
    configuration = client.get_workspace_configuration(state.workspace_id)
    payload = dict(configuration["payload"])
    analyses = dict(payload.get("analyses") or {})
    ic = dict(analyses.get("ic") or {})
    ic["forward_return_horizons"] = (
        {"sampling": "scale_aware"}
        if sampling == "scale_aware" else {
            "bases": list(bases) or ["signal"],
            "multipliers": list(multipliers) or [1],
        }
    )
    if entry_delay_bars:
        ic["ic_lags"] = list(dict.fromkeys(entry_delay_bars))
    analyses["ic"] = ic
    payload["analyses"] = analyses
    value = client.update_workspace_configuration(
        state.workspace_id,
        expected_revision=state.configuration_revision,
        payload=payload,
    )
    state.configuration_revision = int(value["revision"])
    save_state(state)
    click.echo(_json({
        "workspace_id": state.workspace_id,
        "configuration_revision": state.configuration_revision,
        "forward_return_horizons": ic["forward_return_horizons"],
        "entry_delay_bars": ic.get("ic_lags", [0]),
    }))


@workspace.command("ic-rolling")
@click.option(
    "--signal-count", "signal_counts", multiple=True, type=click.IntRange(min=2),
    help="按信号观测数计算的滚动窗口 K；可重复。",
)
@click.option(
    "--clear", is_flag=True,
    help="移除滚动窗口配置，后续 IC 任务不计算 rolling 稳定性。",
)
@friendly_errors
def workspace_ic_rolling(
    signal_counts: tuple[int, ...], clear: bool,
) -> None:
    """Set rolling IC windows by valid signal-observation count only."""
    if clear and signal_counts:
        raise click.ClickException("--clear 不能与 --signal-count 同时使用")
    if not clear and not signal_counts:
        raise click.ClickException("请提供 --signal-count，或使用 --clear 清除")
    state = _require_workspace()
    client = client_from_config()
    configuration = client.get_workspace_configuration(state.workspace_id)
    payload = dict(configuration["payload"])
    analyses = dict(payload.get("analyses") or {})
    ic = dict(analyses.get("ic") or {})
    if clear:
        ic.pop("rolling_windows", None)
        ic.pop("rolling_window", None)
    else:
        ic["rolling_windows"] = {
            "signal_counts": list(dict.fromkeys(signal_counts)),
        }
    analyses["ic"] = ic
    payload["analyses"] = analyses
    value = client.update_workspace_configuration(
        state.workspace_id,
        expected_revision=state.configuration_revision,
        payload=payload,
    )
    state.configuration_revision = int(value["revision"])
    save_state(state)
    click.echo(_json({
        "workspace_id": state.workspace_id,
        "configuration_revision": state.configuration_revision,
        "rolling_windows": ic.get("rolling_windows"),
    }))


@workspace.command("ic-metrics")
@click.option(
    "--metric", "metrics", multiple=True,
    help="保留的 IC 统计字段或统计组（如 core、inference、holding_half_life）；可重复。",
)
@click.option(
    "--exclude", "excluded", multiple=True,
    help="从选择中排除的 IC 统计字段或统计组；可重复。",
)
@click.option(
    "--all", "select_all", is_flag=True,
    help="恢复默认全量 IC 统计字段。",
)
@friendly_errors
def workspace_ic_metrics(
    metrics: tuple[str, ...], excluded: tuple[str, ...], select_all: bool,
) -> None:
    """Select the IC diagnostics projected into each subsequent result.

    Example: ``workspace ic-metrics --metric core --metric inference
    --exclude persistence``.  Omit the setting (or use ``--all``) for the
    default complete diagnostic set.
    """
    if select_all and (metrics or excluded):
        raise click.ClickException("--all 不能与 --metric/--exclude 同时使用")
    if not select_all and not metrics and not excluded:
        raise click.ClickException("请提供 --metric/--exclude，或使用 --all 恢复全量")
    state = _require_workspace()
    client = client_from_config()
    configuration = client.get_workspace_configuration(state.workspace_id)
    payload = dict(configuration["payload"])
    analyses = dict(payload.get("analyses") or {})
    ic = dict(analyses.get("ic") or {})
    if select_all:
        ic.pop("ic_metric_selection", None)
    else:
        ic["ic_metric_selection"] = {
            "include": list(metrics),
            "exclude": list(excluded),
        }
    analyses["ic"] = ic
    payload["analyses"] = analyses
    value = client.update_workspace_configuration(
        state.workspace_id,
        expected_revision=state.configuration_revision,
        payload=payload,
    )
    state.configuration_revision = int(value["revision"])
    save_state(state)
    click.echo(_json({
        "workspace_id": state.workspace_id,
        "configuration_revision": state.configuration_revision,
        "ic_metric_selection": ic.get("ic_metric_selection"),
    }))


@workspace.command("templates")
@friendly_errors
def workspace_templates() -> None:
    for item in client_from_config().list_configuration_templates():
        click.echo(
            f"{item.get('configuration_id')} revision={item.get('revision')} "
            f"name={item.get('name') or '-'}"
        )


@workspace.command("save-template")
@click.argument("name")
@friendly_errors
def workspace_save_template(name: str) -> None:
    state = _require_workspace()
    value = client_from_config().save_configuration_template(state.workspace_id, name=name)
    click.echo(
        f"configuration_id={value.get('configuration_id')} name={value.get('name')} "
        f"source_workspace_id={state.workspace_id}"
    )


@workspace.command("load-template")
@click.argument("configuration_id")
@friendly_errors
def workspace_load_template(configuration_id: str) -> None:
    state = _require_workspace()
    value = client_from_config().load_configuration_template(
        state.workspace_id,
        expected_revision=state.configuration_revision,
        configuration_id=configuration_id,
    )
    state.configuration_revision = int(value["revision"])
    save_state(state)
    click.echo(
        f"workspace_id={state.workspace_id} "
        f"configuration_revision={state.configuration_revision} "
        f"loaded_from={configuration_id}"
    )


@workspace.command("snapshot-create")
@click.argument("name")
@click.option("--source-workspace-id", required=True)
@click.option("--source-configuration-id", required=True)
@click.option("--source-revision", required=True, type=click.IntRange(min=1))
@friendly_errors
def workspace_snapshot_create(
    name: str,
    source_workspace_id: str,
    source_configuration_id: str,
    source_revision: int,
) -> None:
    state = _require_workspace()
    value = client_from_config().create_configuration_snapshot(
        state.workspace_id,
        source_workspace_id=source_workspace_id,
        source_configuration_id=source_configuration_id,
        source_configuration_revision=source_revision,
        name=name,
    )
    click.echo(_json(value))


@workspace.command("snapshot-list")
@friendly_errors
def workspace_snapshot_list() -> None:
    state = _require_workspace()
    click.echo(_json(
        client_from_config().list_configuration_snapshots(
            state.workspace_id
        )
    ))


@click.group("run")
@click.option("--port", "run_ports", multiple=True, type=click.IntRange(1, 65535), help="提交到指定 FactorTester 端口。")
def run(run_ports: tuple[int, ...]) -> None:
    """Submit and inspect immutable research runs."""


@run.command("preview")
@click.option("--analysis", "analyses", multiple=True, type=click.Choice([
    "backtest", "ic", "factor_evaluation", "factor_type_analysis",
]), required=True)
@click.option("--retain-full", is_flag=True, help="预览完整结果保留模式。")
@click.option("--output", "output_requests", multiple=True, help="预先生成的 Job 输出名，可重复；先用 job output-capabilities 查看。")
@click.option("--configuration-snapshot-id", default="")
@click.option(
    "--configuration-snapshot-revision",
    type=click.IntRange(min=1),
)
@click.option(
    "--step",
    "step_mode",
    is_flag=True,
    help="预览逐 flow backtest 模式。",
)
@click.option(
    "--flow-profile",
    is_flag=True,
    help="启用可插拔的累计 Flow 计时；不改变 RunSpec 身份。",
)
@click.option(
    "--flow-profile-min-ms",
    type=click.FloatRange(min=0),
    default=1000.0,
    show_default=True,
    help="仅报告累计耗时达到该阈值的 Flow。",
)
@click.option(
    "--margin-execution-profile",
    is_flag=True,
    help="启用可插拔的保证金检查计数与阶段计时。",
)
@click.option(
    "--profile-factor-worktree",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help=(
        "本次预览上传的 Profile factor-worktree；只上传 custom_factors/*.py，"
        "提交后作为 Job 输入保留。"
    ),
)
@click.option(
    "--factor-set-ref", "factor_set_refs", multiple=True,
    help="将本地 CLI 已验证的冻结因子集合绑定到本次 RunSpec，可重复",
)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--strategy-spec",
    "strategy_spec_paths",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="本次预览使用的 StrategySpec JSON/YAML，可重复。",
)
@click.option(
    "--profile-strategy-worktree",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help=(
        "本次预览上传的 Profile strategy-worktree；提交后作为 Job 输入保留，"
        "清空任务文件时一并删除。"
    ),
)
@run_input_option
@friendly_errors
def run_preview(
    analyses: tuple[str, ...],
    retain_full: bool,
    output_requests: tuple[str, ...],
    configuration_snapshot_id: str,
    configuration_snapshot_revision: int | None,
    step_mode: bool,
    flow_profile: bool,
    flow_profile_min_ms: float,
    margin_execution_profile: bool,
    profile_factor_worktree: Path | None,
    factor_set_refs: tuple[str, ...],
    release_profile: Path | None,
    strategy_spec_paths: tuple[Path, ...],
    profile_strategy_worktree: Path | None,
    run_input_specs: tuple[str, ...],
) -> None:
    """Preview the exact frozen RunSpec identity without creating state."""
    state = _require_workspace()
    snapshot_options = (
        {
            "configuration_snapshot_id": configuration_snapshot_id,
            "configuration_snapshot_revision": (
                configuration_snapshot_revision
            ),
        }
        if configuration_snapshot_id
        else {}
    )
    preview_kwargs = {
        "analyses": list(analyses),
        "retention_mode": "full" if retain_full else "summary",
        "step_mode": step_mode,
        **snapshot_options,
    }
    if flow_profile:
        preview_kwargs["performance_profile"] = {
            "kind": "cumulative_flow",
            "min_total_ms": flow_profile_min_ms,
        }
    if margin_execution_profile:
        preview_kwargs["margin_execution_profile"] = {
            "kind": "cumulative",
        }
    if profile_factor_worktree is not None:
        preview_kwargs["transient_factor_sources"] = _load_profile_factor_sources(
            profile_factor_worktree
        )
    descriptors = _load_factor_set_descriptors(
        factor_set_refs, release_profile=release_profile,
    )
    if descriptors:
        preview_kwargs["factor_subject_descriptors"] = descriptors
    specs = _load_strategy_specs(strategy_spec_paths)
    if specs:
        preview_kwargs["strategy_specs"] = specs
    if profile_strategy_worktree is not None:
        preview_kwargs["transient_strategy_sources"] = _load_strategy_bundle(
            profile_strategy_worktree
        )
    dependencies = load_run_input_dependencies(
        run_input_specs, analyses=analyses,
    )
    if dependencies:
        preview_kwargs["run_input_dependencies"] = dependencies
    if output_requests:
        preview_kwargs["output_requests"] = list(output_requests)
    result = client_from_config().preview_run(
        state.workspace_id,
        None if configuration_snapshot_id else state.configuration_revision,
        **preview_kwargs,
    )
    click.echo(_json(result))


@run.command("submit")
@click.option("--analysis", "analyses", multiple=True, type=click.Choice([
    "backtest", "ic", "factor_evaluation", "factor_type_analysis",
]), required=True)
@click.option("--retain-full", is_flag=True, help="在服务器配额内保留完整曲线和明细。")
@click.option("--output", "output_requests", multiple=True, help="预先生成的 Job 输出名，可重复；先用 job output-capabilities 查看。")
@click.option("--configuration-snapshot-id", default="")
@click.option(
    "--configuration-snapshot-revision",
    type=click.IntRange(min=1),
)
@click.option("--step", "step_mode", is_flag=True, help="逐 flow 暂停，仅支持单个 backtest。")
@click.option(
    "--flow-profile",
    is_flag=True,
    help="启用可插拔的累计 Flow 计时；不改变 RunSpec 身份。",
)
@click.option(
    "--flow-profile-min-ms",
    type=click.FloatRange(min=0),
    default=1000.0,
    show_default=True,
    help="仅报告累计耗时达到该阈值的 Flow。",
)
@click.option(
    "--margin-execution-profile",
    is_flag=True,
    help="启用可插拔的保证金检查计数与阶段计时。",
)
@click.option(
    "--profile-factor-worktree",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help=(
        "本次 Run 上传的 Profile factor-worktree；源码作为 Job 输入保留，"
        "清空任务文件时一并删除。"
    ),
)
@click.option(
    "--factor-set-ref", "factor_set_refs", multiple=True,
    help="将本地 CLI 已验证的冻结因子集合绑定到本次 RunSpec，可重复",
)
@click.option(
    "--strategy-spec",
    "strategy_spec_paths",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="本次 Run 使用的 StrategySpec JSON/YAML，可重复。",
)
@click.option(
    "--profile-strategy-worktree",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help=(
        "本次 Run 上传的 Profile strategy-worktree；源码作为 Job 输入保留，"
        "清空任务文件时一并删除。"
    ),
)
@run_input_option
@click.option(
    "--trial-binding-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="绑定 Research Graph 或 trial-plan create 冻结的 TrialPlan JSON。",
)
@click.option("--profile", "report_profile_id", default="")
@click.option("--work-package-id", "report_work_package_id", default="")
@click.option("--branch-id", "report_branch_id", default="")
@click.option(
    "--report-parent-id",
    default="",
    help="图外 Trial 结果挂载到的现有报告组件 ID。",
)
@click.option(
    "--release-profile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--without-report",
    is_flag=True,
    help="明确提交不写入研究报告的 Trial Job。",
)
@click.option(
    "--wait-report/--no-wait-report",
    default=True,
    help="报告绑定任务完成后由当前 CLI 自动挂载结果。",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="输出 RunSpec 报告投影、运行与 Job 的完整机器可读响应。",
)
@friendly_errors
def run_submit(
    analyses: tuple[str, ...],
    retain_full: bool,
    output_requests: tuple[str, ...],
    configuration_snapshot_id: str,
    configuration_snapshot_revision: int | None,
    step_mode: bool,
    flow_profile: bool,
    flow_profile_min_ms: float,
    margin_execution_profile: bool,
    trial_binding_file: Path | None,
    report_profile_id: str,
    report_work_package_id: str,
    report_branch_id: str,
    report_parent_id: str,
    release_profile: Path | None,
    without_report: bool,
    wait_report: bool,
    profile_factor_worktree: Path | None,
    factor_set_refs: tuple[str, ...],
    strategy_spec_paths: tuple[Path, ...],
    profile_strategy_worktree: Path | None,
    run_input_specs: tuple[str, ...],
    as_json: bool,
) -> None:
    state = _require_workspace()
    trial_binding = None
    if trial_binding_file is not None:
        trial_binding = json.loads(
            trial_binding_file.read_text(encoding="utf-8")
        )
        if not isinstance(trial_binding, dict):
            raise click.ClickException(
                "trial binding JSON must be an object"
            )
    report_scope_values = (
        report_profile_id,
        report_work_package_id,
        report_branch_id,
    )
    has_report_scope = all(report_scope_values)
    is_direct_trial = bool(
        trial_binding
        and trial_binding.get("binding_origin") == "agent_direct"
    )
    if any(report_scope_values) and not has_report_scope:
        raise click.ClickException(
            "--profile、--work-package-id 与 --branch-id 必须同时提供"
        )
    if without_report and has_report_scope:
        raise click.ClickException(
            "--without-report 不能与报告范围同时使用"
        )
    if report_parent_id and not has_report_scope:
        raise click.ClickException(
            "--report-parent-id 只能与完整报告范围同时使用"
        )
    if has_report_scope and is_direct_trial and not report_parent_id:
        raise click.ClickException(
            "图外 Trial 绑定报告时必须提供 --report-parent-id"
        )
    if report_parent_id and not is_direct_trial:
        raise click.ClickException(
            "--report-parent-id 仅用于 agent_direct TrialPlan"
        )
    if has_report_scope and trial_binding is None:
        raise click.ClickException(
            "报告绑定需要 --trial-binding-file 以冻结 Graph 执行身份"
        )
    if trial_binding is not None and not has_report_scope and not without_report:
        raise click.ClickException(
            "研究 Trial Job 必须绑定报告范围；若该任务明确不写报告，"
            "请使用 --without-report"
        )
    report_binding = None
    report_scope = None
    if has_report_scope:
        report_scope = resolve_branch_report_scope(
            client_root=load_profile_root(release_profile),
            profile_id=report_profile_id,
            work_package_id=report_work_package_id,
            branch_id=report_branch_id,
        )
        try:
            if is_direct_trial:
                report_binding = freeze_report_binding(
                    report_scope,
                    trial_binding=trial_binding or {},
                    report_parent_id=report_parent_id,
                )
            else:
                report_binding = freeze_report_binding(
                    report_scope,
                    trial_binding=trial_binding or {},
                )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    snapshot_options = (
        {
            "configuration_snapshot_id": configuration_snapshot_id,
            "configuration_snapshot_revision": (
                configuration_snapshot_revision
            ),
        }
        if configuration_snapshot_id
        else {}
    )
    submit_kwargs = {
        "analyses": list(analyses),
        "retention_mode": "full" if retain_full else "summary",
        "step_mode": step_mode,
        "trial_binding": trial_binding,
        "report_binding": report_binding,
        **snapshot_options,
    }
    if flow_profile:
        submit_kwargs["performance_profile"] = {
            "kind": "cumulative_flow",
            "min_total_ms": flow_profile_min_ms,
        }
    if margin_execution_profile:
        submit_kwargs["margin_execution_profile"] = {
            "kind": "cumulative",
        }
    if profile_factor_worktree is not None:
        submit_kwargs["transient_factor_sources"] = _load_profile_factor_sources(
            profile_factor_worktree
        )
    descriptors = _load_factor_set_descriptors(
        factor_set_refs, release_profile=release_profile,
    )
    if descriptors:
        submit_kwargs["factor_subject_descriptors"] = descriptors
    specs = _load_strategy_specs(strategy_spec_paths)
    if specs:
        submit_kwargs["strategy_specs"] = specs
    if profile_strategy_worktree is not None:
        submit_kwargs["transient_strategy_sources"] = _load_strategy_bundle(
            profile_strategy_worktree
        )
    dependencies = load_run_input_dependencies(
        run_input_specs, analyses=analyses,
    )
    if dependencies:
        submit_kwargs["run_input_dependencies"] = dependencies
    if output_requests:
        submit_kwargs["output_requests"] = list(output_requests)
    client = client_from_config()
    result = client.submit_run(
        state.workspace_id,
        None if configuration_snapshot_id else state.configuration_revision,
        **submit_kwargs,
    )
    if report_scope is not None and wait_report:
        collections = []
        for item in result.get("jobs") or []:
            job_id = str(item.get("job_id") or "")
            if not job_id:
                continue
            for _event in client.stream_job_id(job_id, after=0):
                pass
            collections.append(
                collect_job_report(
                    client,
                    job_id=job_id,
                    scope=report_scope,
                )
            )
        result = {**result, "report_collections": collections}
    if as_json:
        click.echo(_json(result))
        return
    click.echo(f"run_id={result.get('run_id')}")
    for item in result.get("jobs") or []:
        click.echo(f"job_id={item.get('job_id')} kind={item.get('kind')} status={item.get('status')}")
    for collection in result.get("report_collections") or []:
        follow_up = collection.get("report_follow_up") or {}
        click.echo(
            f"report_parent_id={follow_up.get('parent_id')} "
            f"status={follow_up.get('status')}"
        )
        click.echo(str(follow_up.get("message") or ""))


@run.command("show")
@click.argument("run_id")
@friendly_errors
def run_show(run_id: str) -> None:
    click.echo(_json(client_from_config().get_run(run_id)))


@run.command("clone-workspace")
@click.argument("run_id")
@click.option("--title", default="", help="新工作区标题。")
@friendly_errors
def run_clone_workspace(run_id: str, title: str) -> None:
    workspace = client_from_config().clone_run_workspace(run_id, title=title)
    state = load_state()
    state.workspace_id = str(workspace["workspace_id"])
    state.configuration_revision = int(workspace["configuration"]["revision"])
    save_state(state)
    click.echo(
        f"workspace_id={state.workspace_id} "
        f"configuration_revision={state.configuration_revision} source_run_id={run_id}"
    )


@click.group("job")
@click.option("--port", "job_ports", multiple=True, type=click.IntRange(1, 65535), help="操作指定 FactorTester 端口的任务。")
def job(job_ports: tuple[int, ...]) -> None:
    """Observe and control durable job attempts."""


@job.command("list")
@click.option("--all-workspaces", is_flag=True)
@click.option("--kind", type=click.Choice([
    "backtest", "ic", "factor_evaluation", "factor_type_analysis",
    ]))
@click.option("--status", "statuses", multiple=True, type=click.Choice([
    "submitted", "planning", "awaiting_confirmation", "queued", "running",
    "paused", "succeeded", "failed", "cancelled",
]))
@click.option("--limit", default=20, show_default=True, type=click.IntRange(1, 200))
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def job_list(
    all_workspaces: bool, kind: str | None, statuses: tuple[str, ...], limit: int,
    as_json: bool,
) -> None:
    state = load_state()
    workspace_id = "" if all_workspaces else state.workspace_id
    ports = requested_ports() or (None,)
    rows = []
    for port in ports:
        client = client_from_config() if port is None else client_from_config(port=port)
        kwargs = {
            "workspace_id": workspace_id,
            "status": ",".join(statuses),
            "kind": kind or "",
            "limit": limit,
        }
        if port is not None:
            kwargs["all_ports"] = False
        rows.extend(client.list_jobs(**kwargs))
    rows.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    rows = rows[:limit * len(ports)]
    if as_json:
        click.echo(_json({"jobs": rows, "count": len(rows)}))
        return
    for item in rows:
        click.echo(
            f"{item.get('job_id')} run={item.get('run_id')} kind={item.get('kind')} "
            f"status={item.get('status')} attempt={item.get('attempt')} "
            f"port={item.get('port') or (item.get('server_context') or {}).get('port') or '-'}"
        )


@job.command("ports")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def job_ports(as_json: bool) -> None:
    """列出 manager 发现的 FactorTester 任务端口。"""
    ports = client_from_config().list_job_ports()
    if as_json:
        click.echo(_json({"ports": ports, "count": len(ports)}))
        return
    click.echo("、".join(str(port) for port in ports) if ports else "暂无可用任务端口")


@job.command("status")
@click.argument("job_id")
@friendly_errors
def job_status(job_id: str) -> None:
    click.echo(_json(client_from_config().get_job(job_id)))


@job.command("config")
@click.argument("job_id")
@friendly_errors
def job_config(job_id: str) -> None:
    """Print the immutable configuration and output declaration for a Job."""
    detail = client_from_config().get_job(job_id)
    canonical = detail.get("task_detail") or detail
    job = canonical.get("job") or detail
    click.echo(_json({
        "job_id": job_id,
        "run_id": job.get("run_id"),
        "kind": job.get("kind"),
        "run_spec_hash": job.get("run_spec_hash"),
        "factor_source_policy": (
            job.get("factor_source_policy")
            or detail.get("factor_source_policy")
            or {}
        ),
        "output_requests": canonical.get("output_requests") or detail.get("output_requests") or [],
        "server_context": job.get("server_context") or detail.get("server_context") or {},
        "caller": canonical.get("caller") or detail.get("submission_context") or {},
        "research_binding": canonical.get("research_binding") or detail.get("research_binding") or {},
        "configuration": canonical.get("configuration", detail.get("configuration")),
    }))


@job.command("result")
@click.argument("job_id")
@friendly_errors
def job_result(job_id: str) -> None:
    """Read the retained result, cancellation detail, or failure traceback."""
    click.echo(_json(client_from_config().job_result(job_id)))


@job.command("ic-summary")
@click.argument("job_id")
@click.option("--factor", "factor_alias", default="", help="只输出指定 factor alias。")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 IC 摘要。")
@friendly_errors
def job_ic_summary(job_id: str, factor_alias: str, as_json: bool) -> None:
    """Render IC means and forward-IC half-amplitude horizons concisely."""
    result = client_from_config().job_result(job_id)
    payload = result.get("result") if isinstance(result.get("result"), dict) else result
    if not payload.get("success"):
        raise click.ClickException(str(payload.get("error") or "IC job did not succeed"))
    rows = []
    for item in payload.get("factors") or []:
        alias = str(item.get("factor_alias") or item.get("alias") or "")
        if factor_alias and factor_alias not in {alias, str(item.get("alias") or "")}:
            continue
        half_life = item.get("forward_ic_half_life") or {}
        stats = item.get("ic_stats_by_forward_horizon") or {}
        primary = str(item.get("primary_forward_return_horizon") or "")
        primary_stats = stats.get(primary, {}).get("0", {}) if primary else {}
        rows.append({
            "factor_alias": alias,
            "primary_forward_return_horizon": primary,
            "mean_ic": primary_stats.get("mean"),
            "ir": primary_stats.get("IR"),
            "t_stat": primary_stats.get("t_stat"),
            "forward_ic_half_life": half_life,
        })
    if factor_alias and not rows:
        raise click.ClickException(f"IC result does not contain factor {factor_alias!r}")
    if as_json:
        click.echo(_json({"job_id": job_id, "factors": rows}))
        return
    for row in rows:
        half_life = row["forward_ic_half_life"]
        half_text = half_life.get("duration") or half_life.get("status", "unavailable")
        click.echo(
            f"{row['factor_alias']}\tH={row['primary_forward_return_horizon']}\t"
            f"IC={row['mean_ic']}\tIR={row['ir']}\tt={row['t_stat']}\t"
            f"forward_half_life={half_text}"
        )


@job.command("watch")
@click.argument("job_id")
@click.option("--after", default=0, type=int)
@click.option("--json", "as_json", is_flag=True, help="原样输出完整 SSE 事件 JSON。")
@friendly_errors
def job_watch(
    job_id: str, after: int, as_json: bool,
) -> None:
    client = client_from_config()
    for event in client.stream_job_id(job_id, after=after):
        if as_json or event.get("event") != "step" or not isinstance(event.get("data"), dict):
            click.echo(_json(event))
            continue
        for line in render_step_event(event["data"]):
            click.echo(line, color=True)


@job.command("watch-report")
@click.argument("job_id")
@click.option("--after", default=0, type=int)
@scope_options
@friendly_errors
def job_watch_report(
    job_id: str, after: int, profile_id: str, work_package_id: str,
    branch_id: str, release_profile: Path | None,
) -> None:
    """Watch one Job, then collect report-ready outputs into its exact node."""
    client = client_from_config()
    for event in client.stream_job_id(job_id, after=after):
        if event.get("event") != "step" or not isinstance(event.get("data"), dict):
            click.echo(_json(event))
            continue
        for line in render_step_event(event["data"]):
            click.echo(line, color=True)
    scope = resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
    value = collect_job_report(client, job_id=job_id, scope=scope)
    click.echo(_json({"report_collection": value}))


@job.command("progress")
@click.argument("job_id")
@click.option("--after", default=0, type=int)
@friendly_errors
def job_progress(job_id: str, after: int) -> None:
    """Stream compact progress; this is the one live HTTP/SSE operation."""
    for event in client_from_config().stream_job_id(job_id, after=after):
        if event.get("event") not in {"status", "progress", "signal_progress", "activity", "plan", "result", "error", "heartbeat"}:
            continue
        click.echo(_json(event))


@job.command("step-field")
@click.argument("job_id")
@click.argument("qualified_field")
@click.option("--after", default=0, type=int, help="从指定 SSE 序号之后开始读取。")
@friendly_errors
def job_step_field(job_id: str, qualified_field: str, after: int) -> None:
    """打印下一个 step 中指定全限定字段的完整序列化记录。"""
    for event in client_from_config().stream_job_id(job_id, after=after):
        if event.get("event") != "step" or not isinstance(event.get("data"), dict):
            continue
        occurrences = field_occurrences(event["data"], qualified_field)
        if not occurrences:
            continue
        click.echo(_json({
            "job_id": job_id,
            "field": qualified_field,
            "step": {
                "timestamp": event["data"].get("timestamp"),
                "flow_id": event["data"].get("flow_id"),
                "flow_phase": event["data"].get("flow_phase"),
            },
            "occurrences": occurrences,
        }))
        return
    raise click.ClickException(f"流已结束，未找到字段 {qualified_field!r}")


@job.command("cancel")
@click.argument("job_id")
@friendly_errors
def job_cancel(job_id: str) -> None:
    click.echo(_json(client_from_config().cancel_job(job_id)))


@job.command("retry")
@click.argument("job_id")
@click.option(
    "--flow-profile",
    is_flag=True,
    help="在新 JobAttempt 中启用累计 Flow 计时。",
)
@click.option(
    "--flow-profile-min-ms",
    type=click.FloatRange(min=0),
    default=1000.0,
    show_default=True,
)
@click.option(
    "--margin-execution-profile",
    is_flag=True,
    help="在新 JobAttempt 中启用保证金检查计数与阶段计时。",
)
@friendly_errors
def job_retry(
    job_id: str,
    flow_profile: bool,
    flow_profile_min_ms: float,
    margin_execution_profile: bool,
) -> None:
    performance_profile = (
        {
            "kind": "cumulative_flow",
            "min_total_ms": flow_profile_min_ms,
        }
        if flow_profile
        else None
    )
    click.echo(_json(client_from_config().retry_job(
        job_id,
        performance_profile=performance_profile,
        margin_execution_profile=(
            {"kind": "cumulative"} if margin_execution_profile else None
        ),
    )))


@job.command("approve")
@click.argument("job_id")
@friendly_errors
def job_approve(job_id: str) -> None:
    click.echo(_json(client_from_config().approve_job(job_id)))


@job.command("pin")
@click.argument("job_id")
@friendly_errors
def job_pin(job_id: str) -> None:
    click.echo(_json(client_from_config().pin_job(job_id)))


@job.command("unpin")
@friendly_errors
def job_unpin() -> None:
    click.echo(_json(client_from_config().unpin_job()))


@job.command("continue")
@click.argument("job_id")
@click.option("--until", default="", help="Replay until this timestamp, then pause.")
@click.option("--end", "run_to_end", is_flag=True, help="Run the remaining backtest without pausing.")
@click.option("--json", "as_json", is_flag=True, help="输出完整 job 响应。")
@friendly_errors
def job_continue(job_id: str, until: str, run_to_end: bool, as_json: bool) -> None:
    if until and run_to_end:
        raise click.ClickException("--until and --end are mutually exclusive")
    action = "end" if run_to_end else "continue"
    result = client_from_config().continue_job(job_id, action=action, until=until)
    if as_json:
        click.echo(_json(result))
        return
    click.echo(
        f"job_id={result.get('job_id') or job_id} "
        f"status={result.get('status') or '-'} action={action}"
        + (f" until={until}" if until else "")
    )


@job.command("artifact")
@click.argument("job_id")
@click.argument("name")
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="写入本地文件；不会把二进制内容打印进 Agent 上下文。",
)
@friendly_errors
def job_artifact(job_id: str, name: str, output: Path) -> None:
    response = client_from_config().job_artifact(job_id, name)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.part")
    staging.write_bytes(response.content)
    staging.replace(output)
    click.echo(_json({
        "job_id": job_id,
        "name": name,
        "path": str(output),
        "content_type": response.content_type,
        "content_hash": hashlib.sha256(response.content).hexdigest(),
        "size_bytes": len(response.content),
    }))


@job.command("download-all")
@click.argument("job_id")
@click.option(
    "--output",
    required=False,
    type=click.Path(file_okay=False, path_type=Path),
    help="写入本地目录；省略时写入 ~/Documents/FactorTester/jobs/<job_id>。",
)
@friendly_errors
def job_download_all(job_id: str, output: Path | None) -> None:
    client = client_from_config()
    if output is None:
        output = job_cache_directory(job_id)
    output = output.expanduser().resolve()
    files = []
    size_bytes = 0
    for artifact in client.list_job_artifacts(job_id):
        if str(artifact.get("state") or "active") != "active":
            continue
        name = str(artifact.get("name") or "").strip()
        if not name:
            continue
        target = artifact_destination(output, artifact)
        receipt = client.job_artifact_to_path(job_id, name, target)
        files.append(target)
        size_bytes += int(receipt["size_bytes"])
    click.echo(_json({
        "job_id": job_id,
        "path": str(output),
        "files": [str(path) for path in files],
        "size_bytes": size_bytes,
    }))


@job.command("collect-report")
@click.argument("job_id")
@scope_options
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON。")
@friendly_errors
def job_collect_report(
    job_id: str, profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, as_json: bool,
) -> None:
    """Attach terminal Job tables and images to its exact Work Package node."""
    scope = resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
    value = collect_job_report(
        client_from_config(), job_id=job_id, scope=scope,
    )
    click.echo(_json(value) if as_json else "\n".join(
        f"{key}: {item}" for key, item in value.items()
    ))


@job.command("output-capabilities")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读能力声明。")
@friendly_errors
def job_output_capabilities(as_json: bool) -> None:
    capabilities = client_from_config().job_artifact_capabilities()
    if as_json:
        click.echo(_json({"outputs": capabilities}))
        return
    for item in capabilities:
        requires = ",".join(item.get("requires") or ()) or "无"
        modes = ",".join(mode for mode in ("before_run", "after_run") if item.get(mode))
        click.echo(f"{item.get('name')}\t{item.get('label')}\t{modes}\t依赖: {requires}")


@job.command("artifacts")
@click.argument("job_id")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 artifact 元数据。")
@friendly_errors
def job_artifacts(job_id: str, as_json: bool) -> None:
    artifacts = client_from_config().list_job_artifacts(job_id)
    if as_json:
        click.echo(_json({"job_id": job_id, "artifacts": artifacts}))
        return
    for item in artifacts:
        click.echo(f"{item.get('name')}\t{item.get('state')}\t{item.get('size_bytes')} bytes")


@job.command("generate")
@click.argument("job_id")
@click.option("--output", "output_requests", multiple=True, required=True, help="事后生成的输出名，可重复。")
@friendly_errors
def job_generate(job_id: str, output_requests: tuple[str, ...]) -> None:
    click.echo(_json(client_from_config().generate_job_artifacts(
        job_id, output_requests=list(output_requests),
    )))


@job.command("clear-results")
@click.argument("job_id", required=False)
@click.option("--workspace", "current_workspace", is_flag=True, help="清除当前工作区的完整结果。")
@click.option("--all", "all_results", is_flag=True, help="清除当前用户的全部完整结果。")
@friendly_errors
def job_clear_results(job_id: str | None, current_workspace: bool, all_results: bool) -> None:
    selected = int(bool(job_id)) + int(current_workspace) + int(all_results)
    if selected != 1:
        raise click.ClickException("请指定 JOB_ID、--workspace 或 --all 三者之一")
    client = client_from_config()
    if job_id:
        result = client.delete_job_artifacts(job_id)
    else:
        workspace_id = _require_workspace().workspace_id if current_workspace else ""
        result = client.delete_user_artifacts(workspace_id=workspace_id)
    click.echo(_json(result))


@job.command("clear-history")
@click.option(
    "--workspace",
    "current_workspace",
    is_flag=True,
    required=True,
    help="删除当前工作区已成功、失败或取消的任务记录；活动任务不受影响。",
)
@friendly_errors
def job_clear_history(current_workspace: bool) -> None:
    state = _require_workspace()
    result = client_from_config().delete_terminal_job_history(
        workspace_id=state.workspace_id,
    )
    click.echo(_json(result))


@job.command("storage")
@friendly_errors
def job_storage() -> None:
    click.echo(_json(client_from_config().job_storage()))
