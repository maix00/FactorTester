"""Runtime FactorEvaluation object for direct factor-series inspection."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import pandas as pd

from server.modules.shared.factor_data_helpers import (
    clip_series_by_tester_range,
    find_factor as _find_factor,
    match_product_column as _match_product_column,
    series_to_frontend,
)
from server.modules.shared.factor_tester_runtime import create_factor_tester_for_run
from server.modules.shared.submission_helpers import product_attrs
from server.modules.shared.submission_model import ProductPathSelection
from server.services.factor_registry import get_factor_family_instance
from server.services.session_runtime import current_user_obj, get_session_params


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

    def run(self) -> dict[str, Any]:
        started_at = time.time()
        tester = create_factor_tester_for_run(
            self.selection,
            page_uuid=self.page_uuid,
            user=current_user_obj(),
        )
        factor_family = get_factor_family_instance(
            self.factor_family_alias,
            page_uuid=self.page_uuid,
        )
        factors = factor_family.get_factors(
            params_list=get_session_params(self.factor_family_alias, factor_family),
            page_uuid=self.page_uuid,
        )
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
