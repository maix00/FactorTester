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
from server.modules.shared.factor_tester_runtime import create_factor_tester_for_run
from server.modules.shared.factor_tester_runtime import create_isolated_factor_tester_for_run
from server.modules.shared.factor_tester_runtime import selection_from_request
from server.modules.shared.submission_helpers import product_attrs
from tools.products.product_path_selection import ProductPathSelection
from server.services.factor_registry import factor_from_alias, get_factor_family_instance
from server.services.session_runtime import current_user_obj, user_obj_for_name
from tools.data.types import DataTime
from tools.data.types import finest_index


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
        return cls(
            selection=selection,
            factor_family_alias=factor_family_alias,
            factor_alias=factor_alias,
            page_uuid="",
            product_name=str(data.get("product") or "").strip(),
            settings=data.get("settings") if isinstance(data.get("settings"), dict) else None,
            owner=owner,
            run_id=run_id,
            isolated=True,
        )

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
            factor = factor_from_alias(self.factor_alias, username=self.owner)
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

        from tools.factors.FactorTester import _active_tester

        token = _active_tester.set(tester)
        try:
            tester.calc_factor(factor, parallel=False)
        finally:
            _active_tester.reset(token)

        result = tester.results.get(factor)
        table = result.func_table if result is not None and not result.func_table.empty else (
            result.table if result is not None and not result.table.empty else pd.DataFrame()
        )
        if table.empty:
            raise ValueError("因子 evaluate 未返回可显示序列")

        selected_products = sorted(self.selection.products, key=lambda item: getattr(item, "name", str(item)))
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
            meta = product_attrs(product, "name", "desc")
            series_items.append({
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
            })

        if not series_items:
            raise LookupError("所选产品没有该因子的可显示序列")
        return {
            "success": True,
            "factor": {
                "alias": getattr(factor, "alias", self.factor_alias),
                "name": getattr(factor, "name", self.factor_alias),
                "freq": getattr(getattr(factor, "freq", None), "name", ""),
            },
            "products": [product_attrs(product, "name", "desc") for product in selected_products],
            "series": series_items,
            "meta": {
                "elapsed_ms": round((time.time() - started_at) * 1000),
                "product_count": len(series_items),
            },
        }

    def _run_window_datetimes(self) -> tuple[DataTime | None, DataTime | None]:
        settings = self.settings or {}
        start_date = str(settings.get("start_date") or "").strip()
        end_date = str(settings.get("end_date") or "").strip()
        if not start_date or not end_date:
            return None, None
        precision = str(settings.get("time_precision") or "exact")
        if precision == "trading_day":
            timezone = str(settings.get("timezone") or "UTC")
            start = pd.Timestamp(start_date).tz_localize(timezone)
            end = pd.Timestamp(end_date).tz_localize(timezone)
            return DataTime(ts=start, precision="trading_day"), DataTime(ts=end, precision="trading_day")
        timezone = str(settings.get("timezone") or "Asia/Shanghai")
        start_time = str(settings.get("start_time") or "00:00")
        end_time = str(settings.get("end_time") or "23:59")
        start = pd.Timestamp(f"{start_date} {start_time}").tz_localize(timezone)
        end = pd.Timestamp(f"{end_date} {end_time}").tz_localize(timezone)
        return DataTime(ts=start), DataTime(ts=end)

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
