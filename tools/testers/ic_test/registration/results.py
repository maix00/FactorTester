"""IC result projections and authoring list surface."""

from __future__ import annotations

from tools.testers.ic_test.result_projection_contract import (
    ic_result_projection_contracts,
)
from tools.testers.settings.contracts import (
    ResultProjectionDefinition,
    ResultTabDefinition,
    SettingsSurface,
    SurfaceFlow,
    TabMountPoint,
)
from tools.testers.settings.registry import ApplicationSettings


def register_result_contracts(app: ApplicationSettings) -> None:
    _register_result_tabs(app)
    _register_result_projections(app)
    _register_surfaces(app)


def _register_result_tabs(app: ApplicationSettings) -> None:
    for tab in (
        ResultTabDefinition(
            "cross_sectional_rank_ic", "Cross-sectional Rank IC", "ic_method",
            10, default=True, requires={"ic_correlation": ("rank", "both")},
        ),
        ResultTabDefinition(
            "cross_sectional_pearson_ic", "Cross-sectional Pearson IC",
            "ic_method", 20,
            requires={"ic_correlation": ("pearson", "both")},
        ),
        ResultTabDefinition("ic_summary", "IC Summary", "ic_summary", 30),
        ResultTabDefinition("ic_decay", "IC Decay", "ic_delay", 40),
        ResultTabDefinition("rolling_ic", "Rolling IC", "ic_summary", 50),
        ResultTabDefinition(
            "quantile_portfolio_statistics", "Quantile Portfolio Statistics",
            "quantile_portfolio_statistics", 55,
        ),
    ):
        app.register_result_tab(tab)


def ic_result_projections() -> tuple[ResultProjectionDefinition, ...]:
    """Return the canonical IC result surface consumed by every client.

    A projection names only persisted canonical artifacts.  A tab is therefore
    unavailable when its source was not requested or the computation produced
    no rows; the frontend never has to invent an empty capability from a
    setting or an analysis-node name.
    """

    return tuple(
        ResultProjectionDefinition(**item)
        for item in ic_result_projection_contracts()
    )


def _register_result_projections(app: ApplicationSettings) -> None:
    for projection in ic_result_projections():
        app.register_result_projection(projection)


def _register_surfaces(app: ApplicationSettings) -> None:
    app.register_surface(SettingsSurface(
        "local", "IC 本地设置", TabMountPoint.LOCAL_SETTINGS,
        kind="panel", order=10,
    ))
    app.register_surface(SettingsSurface(
        "ic_configs", "配置组设置", TabMountPoint.GROUP_SETTINGS,
        kind="list", order=20, selection="single",
        run_mode="select_then_run", editable=True, item_label="配置组",
        content_adapter="ic_configuration_groups",
    ))
    for flow in (
        SurfaceFlow(
            "ic_configs", "add_config", "新增配置组", "create", order=0,
        ),
        SurfaceFlow(
            "ic_configs", "edit", "编辑", "edit", order=10,
            min_selected=1, max_selected=1,
        ),
        SurfaceFlow(
            "ic_configs", "delete", "删除", "delete", order=20,
            min_selected=1, button_class="btn-outline-danger",
        ),
    ):
        app.register_flow(flow)
