"""Runtime FactorEvaluation object for direct factor-series inspection."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import pandas as pd

from server.modules.factors.helpers import (
    clip_series_by_tester_range,
    find_factor as _find_factor,
    match_product_column as _match_product_column,
    series_to_frontend,
)
from server.modules.single_factor_test.signal_schedule_diagnostics import (
    policy_for_factor,
    summarize_signal_schedule,
)
from server.modules.shared.factor_data_coverage import require_factor_data_coverage, apply_factor_data_coverage
from server.modules.shared.factor_warmup import resolve_factor_warmup_policy
from server.modules.shared.factor_tester_runtime import (
    create_factor_tester_for_run,
    create_isolated_factor_tester_for_run,
    require_run_window,
    selection_from_request,
)
from server.modules.shared.submission_helpers import product_attrs
from tools.products.product_path_selection import ProductPathSelection
from server.services.factor_registry import get_factor_family_instance
from server.services.session_runtime import current_user_obj, user_obj_for_name
from tools.data.types import DataTime
from tools.data.types import finest_index
from tools.factors.formula_identity import require_frozen_factor


@dataclass(slots=True)
class FactorEvaluation:
    """Evaluate one factor on a product path selection.

    This runtime-only object sits beside the IC and group test modules. It owns
    the direct factor-series evaluation flow and creates its FactorTester context
    only for the run.
    """

    selection: ProductPathSelection
    factor_family_alias: str
    factor_alias: str
    page_uuid: str
    product_name: str = ""
    settings: dict[str, Any] | None = None
    owner: str = ""
    run_id: str = ""
    isolated: bool = False
    external_factor_artifacts: list[dict[str, Any]] | None = None
    frozen_factors: list[dict[str, Any]] | None = None
    factor_ref: str = ""

    @classmethod
    def from_request(cls, data: dict[str, Any], *, page_uuid: str) -> "FactorEvaluation":
        paths = data.get("paths") or data.get("selected_paths") or []
        if not isinstance(paths, list) or not paths:
            raise ValueError("请先从产品树选择产品或路径")
        factor_family_alias = str(data.get("factor_family_alias") or "").strip()
        factor_alias = str(data.get("factor_alias") or data.get("factor_name") or "").strip()
        if not factor_family_alias or not factor_alias:
            raise ValueError("请先选择因子")
        selection = ProductPathSelection.from_paths(
            "factor-evaluation",
            paths,
            label="因子评估",
            source_type="factor_evaluation",
            page_uuid=page_uuid,
        )
        return cls(
            selection=selection,
            factor_family_alias=factor_family_alias,
            factor_alias=factor_alias,
            page_uuid=page_uuid,
            product_name=str(data.get("product") or "").strip(),
            settings=data.get("settings") if isinstance(data.get("settings"), dict) else None,
        )

    @classmethod
    def from_run_spec(cls, data: dict[str, Any]) -> "FactorEvaluation":
        owner = str(data.get("_owner") or data.get("owner_username") or "").strip()
        run_id = str(data.get("run_id") or data.get("run_token") or "").strip()
        if not owner or not run_id:
            raise ValueError("factor evaluation RunSpec requires owner and run_id")
        factor_family_alias = str(data.get("factor_family_alias") or "").strip()
        factor_alias = str(data.get("factor_alias") or data.get("factor_name") or "").strip()
        if not factor_family_alias or not factor_alias:
            raise ValueError("请先选择因子")
        selection = selection_from_request(data, page_uuid="")
        nested_settings = data.get("settings")
        # RunSpec v4 materializes ``analysis.execution.settings`` onto the
        # worker payload at the execution boundary.  Keep accepting the older
        # nested shape, but use the flattened execution contract otherwise.
        settings = nested_settings if isinstance(nested_settings, dict) else data
        return cls(
            selection=selection,
            factor_family_alias=factor_family_alias,
            factor_alias=factor_alias,
            page_uuid="",
            product_name=str(data.get("product") or "").strip(),
            settings=settings,
            owner=owner,
            run_id=run_id,
            isolated=True,
            external_factor_artifacts=list(data.get("external_factor_artifacts") or []),
            frozen_factors=list(data.get('factors') or
                ((data.get('run_spec') or {}).get('configuration') or {}).get('shared', {}).get('factors') or []),
            factor_ref=str(data.get('factor_ref') or ''),
        )

    def _resolve_run_factor(self):
        from server.modules.shared.run_spec_resolution.factors import RunFactorResolver

        return RunFactorResolver(
            owner=self.owner,
            frozen_factors=self.frozen_factors,
            external_factor_artifacts=self.external_factor_artifacts,
        ).resolve(factor_ref=self.factor_ref, alias=self.factor_alias)

    def run(self) -> dict[str, Any]:
        started_at = time.time()
        start_dt, end_dt = self._run_window_datetimes()
        tester = (
            create_isolated_factor_tester_for_run(
                self.selection,
                run_id=self.run_id,
                start_dt=start_dt,
                end_dt=end_dt,
                user=user_obj_for_name(self.owner),
            )
            if self.isolated
            else create_factor_tester_for_run(
                self.selection,
                page_uuid=self.page_uuid,
                start_dt=start_dt,
                end_dt=end_dt,
                user=current_user_obj(),
            )
        )
        if self.isolated:
            factor = self._resolve_run_factor()
        else:
            factor = None
        if factor is None:
            factor_family = get_factor_family_instance(
                self.factor_family_alias,
                username=self.owner or None,
                page_uuid=self.page_uuid,
            )
            # Legacy synchronous pages still resolve submitted page factors.
            from server.services.factor_registry import page_factors
            page_dict = page_factors.get(str(self.page_uuid), {})
            family_alias = getattr(factor_family, 'alias', '')
            factors = [
                item for item in page_dict.values()
                if getattr(getattr(item, 'family', None), 'alias', None) == family_alias
            ]
            factor_family.factors = factors
            factor = _find_factor(factors, self.factor_alias, self.factor_alias)
        if factor is None:
            raise LookupError("请先提交参数设置，或从模板加载已有因子")

        warmup = resolve_factor_warmup_policy(
            self.settings, factor, default_mode="none",
        )
        coverage = require_factor_data_coverage(
            tester.products,
            factor,
            start_dt=start_dt,
            end_dt=end_dt,
            data_source=str((self.settings or {}).get("data_source") or ""),
            warmup_window=warmup.evaluation_window(),
            allow_all_warmup_fallback=warmup.mode == "auto",
        )

        runtime_rows = apply_factor_data_coverage(tester, coverage)

        from tools.factors.FactorTester import _active_tester

        token = _active_tester.set(tester)
        try:
            tester.calc_factor(
                factor, parallel=False,
                warmup_window=warmup.evaluation_window(),
            )
        finally:
            _active_tester.reset(token)

        result = tester.results.get(factor)
        raw_table = (
            result.func_table
            if result is not None and not result.func_table.empty
            else pd.DataFrame()
        )
        scheduled_table = (
            result.table
            if result is not None and not result.table.empty
            else pd.DataFrame()
        )
        table = raw_table if not raw_table.empty else scheduled_table
        if table.empty:
            raise ValueError("因子 evaluate 未返回可显示序列")

        selected_products = sorted(tester.products, key=lambda item: getattr(item, "name", str(item)))
        series_items = []
        for product in selected_products:
            name = str(getattr(product, "name", product))
            if self.product_name and name != self.product_name:
                continue
            col = _match_product_column(table, product)
            if col is None:
                continue
            series = table[col].dropna()
            if series.empty:
                continue
            series = clip_series_by_tester_range(series, tester)
            series = self._clip_series_by_run_window(series, start_dt, end_dt)
            dates_out, values = series_to_frontend(
                series,
                factor.freq is not None and factor.freq.is_day_multiple(),
            )
            returns_payload = self._returns_payload(result, product, factor, tester)
            schedule_payload = self._signal_schedule_payload(
                raw_table,
                scheduled_table,
                product,
                factor,
                tester,
                start_dt,
                end_dt,
            )
            meta = product_attrs(product, "name", "desc")
            series_item = {
                "product": name,
                "desc": meta.get("desc") or name,
                "dates": dates_out,
                "values": values,
                "returns": returns_payload,
                "chart": {
                    "x_label": "time",
                    "y_label": "factor",
                    "title": name + " · " + getattr(factor, "alias", self.factor_alias),
                },
            }
            if schedule_payload is not None:
                series_item["signal_schedule"] = schedule_payload
            series_items.append(series_item)
            # Nested layers: expose every intermediate the family computed so the
            # viewer can show what each nesting level contributes.
            for layer_name, frame in _intermediate_series(factor):
                layer_col = _match_product_column(frame, product)
                if layer_col is None:
                    continue
                layer = frame[layer_col].dropna()
                if layer.empty:
                    continue
                layer = clip_series_by_tester_range(layer, tester)
                layer = self._clip_series_by_run_window(layer, start_dt, end_dt)
                if layer.empty:
                    continue
                layer_dates, layer_values = series_to_frontend(
                    layer,
                    factor.freq is not None and factor.freq.is_day_multiple(),
                )
                series_items.append({
                    "product": name,
                    "desc": layer_name,
                    "dates": layer_dates,
                    "values": layer_values,
                    "returns": None,
                    "chart": {
                        "x_label": "time", "y_label": "factor",
                        "title": name + " · " + layer_name,
                    },
                    "layer": layer_name,
                    "nested_of": getattr(factor, "alias", self.factor_alias),
                })

        if not series_items:
            raise LookupError("所选产品没有该因子的可显示序列")
        from server.services.external_factor_artifacts import result_metadata

        return {
            "success": True,
            "factor": {
                "alias": getattr(factor, "alias", self.factor_alias),
                "name": getattr(factor, "name", self.factor_alias),
                "freq": getattr(getattr(factor, "freq", None), "name", ""),
            },
            "products": [product_attrs(product, "name", "desc") for product in selected_products],
            "series": series_items,
            "market": self._market_series(selected_products),
            "meta": {
                "elapsed_ms": round((time.time() - started_at) * 1000),
                "product_count": len(series_items),
                "warmup": warmup.as_dict(),
                "data_coverage": coverage,
            },
            "runtime_info_rows": runtime_rows,
            "external_factor_artifacts": result_metadata(
                self.external_factor_artifacts
            ),
        }


    def _market_series(self, products: list[Any]) -> list[dict[str, Any]]:
        """Load the traded product's OHLCV so a report can draw K线/成交量/持仓量.

        The HTTP projection (``product_market_data.price_series``) resolves
        products from the Manager catalog, which is empty inside a Job worker, so
        the run reads the bars through the product view the tester already uses.
        A failure is recorded in the payload instead of being dropped.
        """
        settings = self.settings or {}
        if not products:
            return []
        adjusted = str(settings.get("price_type") or "adjusted") == "adjusted"
        start_dt, end_dt = self._run_window_datetimes()
        loaded: list[dict[str, Any]] = []
        for product in products[:2]:
            if self.product_name and str(getattr(product, "name", "")) != self.product_name:
                continue
            entry = self._market_entry(product, adjusted, start_dt, end_dt)
            if entry:
                loaded.append(entry)
        return loaded

    @staticmethod
    def _market_entry(
        product: Any, adjusted: bool, start_dt: DataTime, end_dt: DataTime,
    ) -> dict[str, Any]:
        """Return one product's market bars, or the reason they are unavailable."""
        name = str(getattr(product, "name", "") or product)
        available = list(product.list_available_freqs())
        if not available:
            return {"product": name, "bars": [], "reason": "该产品没有可用频率"}
        current = getattr(product, "current_freq", None)
        frequency = current if current in available else available[0]
        try:
            view = getattr(product, frequency.name)
        except AttributeError:
            return {
                "product": name, "bars": [],
                "reason": f"没有 {getattr(frequency, 'name', '')} 数据视图",
            }
        columns = (
            ["OPEN_ADJUSTED", "HIGH_ADJUSTED", "LOW_ADJUSTED", "CLOSE_ADJUSTED", "VOLUME"]
            if adjusted else ["OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]
        )
        reason = ""
        try:
            frame = view.get_and_adjust_cols(
                [*columns, "OPEN_INTEREST"], copy=False,
                start_dt=start_dt, end_dt=end_dt,
            )
        except Exception as error:
            # Not every provider exposes open interest; keep the OHLCV bars and
            # record why the 持仓量 panel is missing.
            reason = f"读取持仓量失败: {type(error).__name__}"
            try:
                frame = view.get_and_adjust_cols(
                    columns, copy=False, start_dt=start_dt, end_dt=end_dt,
                )
            except Exception as second:
                return {
                    "product": name, "bars": [],
                    "reason": f"读取行情失败: {type(second).__name__}",
                }
        bars = FactorEvaluation._market_bars(
            name, frame, adjusted, frequency, reason,
            getattr(product, "timezone", None) or "Asia/Shanghai",
        )
        return bars

    @staticmethod
    def _market_bars(
        name: str, frame: Any, adjusted: bool, frequency: Any,
        reason: str, timezone: str, limit: int = 1200, recent: int = 1500,
    ) -> dict[str, Any]:
        from server.modules.shared.price_data_helpers import (
            format_price_row, open_interest_column,
        )
        if frame is None or getattr(frame, "empty", True):
            return {"product": name, "bars": [], "reason": reason or "区间内没有行情"}
        columns = (
            ("OPEN_ADJUSTED", "HIGH_ADJUSTED", "LOW_ADJUSTED", "CLOSE_ADJUSTED", "VOLUME")
            if adjusted else ("OPEN", "HIGH", "LOW", "CLOSE", "VOLUME")
        )
        interest = open_interest_column(getattr(frame, "columns", []))
        is_daily = bool(getattr(frequency, "is_day_multiple", lambda: False)())
        # Two resolutions: the whole range thinned to LIMIT bars (so the K线 panel
        # spans the same window as the factor layers) and the native-resolution
        # tail (so the intraday window is not averaged away).
        full = frame.copy()
        if len(full) > limit:
            step = max(1, -(-len(full) // limit))
            full = full.iloc[::step]
            reason = (reason + "; " if reason else "") + f"全时段按 1/{step} 抽样"
        recent_frame = frame.tail(recent) if len(frame) > recent else frame
        return {
            "product": name,
            "freq": str(getattr(frequency, "name", "")),
            "adjusted": adjusted,
            **FactorEvaluation._market_columns(name, full, columns, interest, is_daily, timezone,
                                   reason=reason, key="bars"),
            **(
                FactorEvaluation._market_columns(name, recent_frame, columns, interest, is_daily,
                                     timezone, key="recent_bars")
                if len(recent_frame) != len(full) or len(frame) > recent else {}
            ),
        }

    @staticmethod
    def _market_columns(
        name: str, frame: Any, columns: tuple, interest: Any, is_daily: bool,
        timezone: str, *, key: str, reason: str = "",
    ) -> dict[str, Any]:
        from server.modules.shared.price_data_helpers import format_price_row

        emitted = frame.copy()
        # A product view can hand back a MultiIndex (instrument, time); taking the
        # raw index would put tuples into the timestamp column and every row would
        # fail to format.
        index = emitted.index
        emitted["__time__"] = list(finest_index(index) if isinstance(index, pd.MultiIndex) else index)
        bars = [
            format_price_row(
                row=row, time_col="__time__", o_col=columns[0], h_col=columns[1],
                l_col=columns[2], c_col=columns[3], v_col=columns[4],
                oi_col=interest, freq_is_daily=is_daily, timezone=timezone,
            )
            for _, row in emitted.iterrows()
        ]
        return {
            key: bars,
            ("has_open_interest" if key == "bars" else "recent_has_open_interest"):
                any("open_interest" in bar for bar in bars),
            **({"reason": reason} if reason and key == "bars" else {}),
        }

    def _run_window_datetimes(self) -> tuple[DataTime, DataTime]:
        settings = self.settings or {}
        start_date = str(settings.get("start_date") or "").strip()
        end_date = str(settings.get("end_date") or "").strip()
        if not start_date or not end_date:
            return require_run_window(None, None)
        precision = str(settings.get("time_precision") or "exact")
        if precision == "trading_day":
            timezone = str(settings.get("timezone") or "UTC")
            start = pd.Timestamp(start_date).tz_localize(timezone)
            end = pd.Timestamp(end_date).tz_localize(timezone)
            return require_run_window(
                DataTime(ts=start, precision="trading_day"),
                DataTime(ts=end, precision="trading_day"),
            )
        timezone = str(settings.get("timezone") or "Asia/Shanghai")
        start_time = str(settings.get("start_time") or "00:00")
        end_time = str(settings.get("end_time") or "23:59")
        start = pd.Timestamp(f"{start_date} {start_time}").tz_localize(timezone)
        end = pd.Timestamp(f"{end_date} {end_time}").tz_localize(timezone)
        return require_run_window(DataTime(ts=start), DataTime(ts=end))

    @staticmethod
    def _clip_series_by_run_window(
        series: pd.Series,
        start_dt: DataTime | None,
        end_dt: DataTime | None,
    ) -> pd.Series:
        if series.empty or start_dt is None or end_dt is None:
            return series
        if start_dt.precision != "exact" and end_dt.precision != "exact":
            return series
        idx = finest_index(series.index) if isinstance(series.index, pd.MultiIndex) else pd.DatetimeIndex(series.index)

        def _align(ts: pd.Timestamp, index: pd.DatetimeIndex) -> pd.Timestamp:
            tz = getattr(index, "tz", None)
            if tz is not None and ts.tzinfo is None:
                return ts.tz_localize(tz)
            if tz is None and ts.tzinfo is not None:
                return ts.tz_convert(None)
            return ts

        mask = pd.Series(True, index=series.index)
        if start_dt.ts is not None:
            start = _align(pd.Timestamp(start_dt.ts), idx)
            mask &= idx >= start
        if end_dt.ts is not None:
            end = _align(pd.Timestamp(end_dt.ts), idx)
            mask &= idx <= end
        return series.loc[mask.to_numpy()]

    @staticmethod
    def _returns_payload(result: Any, product: Any, factor: Any, tester: Any) -> dict[str, Any] | None:
        if result is None or getattr(result, "returns", pd.DataFrame()).empty:
            return None
        returns_df = result.returns
        if not isinstance(returns_df, pd.DataFrame):
            return None
        ret_col = _match_product_column(returns_df, product)
        if ret_col is None:
            return None
        ret_series = returns_df[ret_col].dropna()
        if ret_series.empty:
            return None
        ret_series = clip_series_by_tester_range(ret_series, tester)
        ret_dates_out, ret_values = series_to_frontend(
            ret_series,
            factor.freq is not None and factor.freq.is_day_multiple(),
        )
        if len(ret_dates_out) and len(ret_dates_out) == len(ret_values):
            return {"dates": ret_dates_out, "values": ret_values}
        return None

    @classmethod
    def _signal_schedule_payload(
        cls,
        raw_table: pd.DataFrame,
        scheduled_table: pd.DataFrame,
        product: Any,
        factor: Any,
        tester: Any,
        start_dt: DataTime | None,
        end_dt: DataTime | None,
    ) -> dict[str, Any] | None:
        """Return compact schedule evidence when both batch views are available."""

        if raw_table.empty or scheduled_table.empty:
            return None
        raw_col = _match_product_column(raw_table, product)
        scheduled_col = _match_product_column(scheduled_table, product)
        if raw_col is None or scheduled_col is None:
            return None
        raw = raw_table[raw_col].dropna()
        scheduled = scheduled_table[scheduled_col].dropna()
        if raw.empty or scheduled.empty:
            return None
        raw = clip_series_by_tester_range(raw, tester)
        scheduled = clip_series_by_tester_range(scheduled, tester)
        raw = cls._clip_series_by_run_window(raw, start_dt, end_dt)
        scheduled = cls._clip_series_by_run_window(scheduled, start_dt, end_dt)
        return summarize_signal_schedule(
            raw,
            scheduled,
            policy=policy_for_factor(factor),
        )

def _intermediate_series(factor: Any, *, limit: int = 12):
    """Yield every intermediate the runtime computed for one factor.

    ``_intermediate_alias_index`` only holds the names the **root** expression
    declared, so nested (and anonymous) layers never reached the report and the
    reader only saw the final value.  Walk the expression tree instead and label
    each node by its declared name, else by the family alias that produced it.
    """
    nodes: list[Any] = []
    expr = getattr(factor, "_expr", None)
    if expr is not None and hasattr(expr, "iter_intermediate_nodes"):
        try:
            nodes = list(expr.iter_intermediate_nodes())
        except Exception:
            nodes = []
    if not nodes:
        index = getattr(factor, "_intermediate_alias_index", None) or {}
        try:
            names = [str(name) for name in index][: max(0, int(limit))]
        except TypeError:
            return
        for name in names:
            try:
                frame = factor.get_intermediate(name)
            except Exception:
                continue
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                yield name, frame
        return
    seen: set[str] = set()
    yielded = 0
    for position, node in enumerate(nodes, start=1):
        if yielded >= max(0, int(limit)):
            break
        try:
            key = node._structural_key()
        except Exception:
            continue
        try:
            frame = factor.get_intermediate(key)
        except Exception:
            continue
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        label = str(getattr(node, "_intermediate_name", "") or "").strip()
        if not label:
            label = str(getattr(node, "factor_alias", "") or "").strip()
        label = label or f"第 {position} 层"
        if label in seen:
            label = f"{label} #{position}"
        seen.add(label)
        yielded += 1
        yield label, frame


def factor_series_for_run_spec(data: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the frozen root factors through the factor-series runtime.

    IC and backtest call this only when ``factor_series`` was requested.  This
    keeps factor reconstruction, coverage, warm-up and value serialization on
    the same path as the dedicated 查看因子序列 test instead of growing a third
    module-specific evaluator.
    """
    records = list(data.get("factors") or (
        ((data.get("run_spec") or {}).get("configuration") or {})
        .get("shared", {}).get("factors") or []
    ))
    combined: list[dict[str, Any]] = []
    factors: list[dict[str, str]] = []
    markets: list[dict[str, Any]] = []
    seen: set[str] = set()
    requested_refs = _requested_factor_refs(data)
    series_scope = {}
    if not any(data.get(key) for key in (
        "product_path_selection", "product_path_selection_id", "selection_id",
        "selected_paths", "paths",
    )):
        # Backtest stores scopes on its groups, not as one top-level selection.
        # These are already the used, exact members frozen at submission.
        # Merge them for the shared series viewer without rereading the library.
        selections = data.get("product_selections") or (
            ((data.get("run_spec") or {}).get("configuration") or {})
            .get("shared", {}).get("product_selections") or {}
        )
        paths = sorted({path for value in selections.values()
                        for path in value.get("paths", [])})
        if paths:
            series_scope = {"selected_paths": paths, "label": "运行涉及产品"}
    for raw in records:
        try:
            record = require_frozen_factor(raw)
        except (TypeError, ValueError):
            continue
        ref = str(record["ref"])
        if requested_refs and ref not in requested_refs:
            continue
        if ref in seen:
            continue
        seen.add(ref)
        identity = record.get("identity") or {}
        request = {
            **data,
            **series_scope,
            "factor_ref": ref,
            "factor_alias": str(record.get("alias") or ""),
            "factor_family_alias": str(identity.get("family_alias") or ""),
        }
        result = FactorEvaluation.from_run_spec(request).run()
        descriptor = {
            "ref": ref, "alias": str(record.get("alias") or ""),
            "family_alias": str(identity.get("family_alias") or ""),
            "freq": str((result.get("factor") or {}).get("freq") or ""),
        }
        factors.append(descriptor)
        for item in result.get("series") or ():
            combined.append({
                **item, "factor_ref": ref,
                "factor_alias": descriptor["alias"], "factor": descriptor,
            })
        # The per-factor evaluation already loaded the traded product's bars for
        # the K线/成交量/持仓量 panels; dropping them here is why an IC/backtest
        # run that requested factor_series mounted charts with no market at all.
        for market in result.get("market") or ():
            if isinstance(market, dict) and market not in markets:
                markets.append(market)
    if not combined:
        raise ValueError("所选运行配置没有可生成的因子序列")
    payload: dict[str, Any] = {
        "schema_version": 1, "factors": factors, "series": combined,
    }
    if markets:
        payload["market"] = markets
    return payload


def factor_series_from_tester(
    tester: Any, factors: list[Any], *, start_dt: DataTime | None = None,
    end_dt: DataTime | None = None,
    factor_refs: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Serialize tables already computed by IC without evaluating factors again."""
    descriptors: list[dict[str, str]] = []
    items: list[dict[str, Any]] = []
    for factor in dict.fromkeys(factors):
        result = tester.results.get(factor)
        table = getattr(result, "func_table", pd.DataFrame())
        if not isinstance(table, pd.DataFrame) or table.empty:
            table = getattr(result, "table", pd.DataFrame())
        if not isinstance(table, pd.DataFrame) or table.empty:
            continue
        descriptor = {
            "ref": str((factor_refs or {}).get(str(getattr(factor, "alias", "")))
                or getattr(factor, "frozen_ref", "") or getattr(factor, "ref", "")),
            "alias": str(getattr(factor, "alias", "") or getattr(factor, "name", "因子")),
            "family_alias": str(getattr(getattr(factor, "family", None), "alias", "")),
            "freq": str(getattr(getattr(factor, "freq", None), "name", "")),
        }
        descriptors.append(descriptor)
        for product in sorted(tester.products, key=lambda value: getattr(value, "name", str(value))):
            column = _match_product_column(table, product)
            if column is None:
                continue
            series = FactorEvaluation._clip_series_by_run_window(
                clip_series_by_tester_range(table[column].dropna(), tester),
                start_dt, end_dt,
            )
            if series.empty:
                continue
            dates, values = series_to_frontend(
                series, bool(getattr(factor, "freq", None)
                    and factor.freq.is_day_multiple()),
            )
            meta = product_attrs(product, "name", "desc")
            item = {
                "product": str(getattr(product, "name", product)),
                "desc": meta.get("desc") or str(getattr(product, "name", product)),
                "dates": dates, "values": values,
                "factor_ref": descriptor["ref"],
                "factor_alias": descriptor["alias"], "factor": descriptor,
            }
            returns = FactorEvaluation._returns_payload(result, product, factor, tester)
            if returns is not None:
                item["returns"] = returns
            for attr, key in (
                ("factor_cs_rank", "cs_rank"),
                ("return_cs_rank", "returns_cs_rank"),
            ):
                panel = getattr(result, attr, None)
                rank_column = _match_product_column(panel, product) \
                    if isinstance(panel, pd.DataFrame) else None
                if rank_column is None:
                    continue
                ranked = FactorEvaluation._clip_series_by_run_window(
                    clip_series_by_tester_range(panel[rank_column].dropna(), tester),
                    start_dt, end_dt,
                )
                rank_dates, rank_values = series_to_frontend(
                    ranked, bool(getattr(factor, "freq", None)
                        and factor.freq.is_day_multiple()),
                )
                item[key] = {"dates": rank_dates, "values": rank_values}
            items.append(item)
    # IC/backtest serialize tables the tester already computed, so the market
    # bars have to be loaded here too or an auto-mounted section shows factor
    # layers with no K线/成交量/持仓量 at all.
    markets = [
        entry for entry in (
            FactorEvaluation._market_entry(product, True, start_dt, end_dt)
            for product in sorted(
                tester.products, key=lambda value: getattr(value, "name", str(value)),
            )
        )
        if entry
    ]
    payload: dict[str, Any] = {
        "schema_version": 1, "factors": descriptors, "series": items,
    }
    if markets:
        payload["market"] = markets
    return payload


def _requested_factor_refs(data: dict[str, Any]) -> set[str]:
    refs: set[str] = set()

    def visit(value: Any, key: str = "") -> None:
        if key in {"factors", "external_factor_artifacts"}:
            return
        if isinstance(value, dict):
            for child_key, child in value.items():
                if child_key == "factor_ref" and isinstance(child, str):
                    refs.add(child)
                elif child_key in {"factor_refs", "factor_candidate_refs"} and isinstance(child, list):
                    refs.update(str(item) for item in child if str(item).startswith("factor:"))
                else:
                    visit(child, child_key)
        elif isinstance(value, list):
            for child in value:
                visit(child, key)

    visit(data)
    return refs
