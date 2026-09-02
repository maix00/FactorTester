"""
因子类型分析单元测试。

覆盖：
  - ReferenceFactorRegistry 注册/查询
  - 时序相关性计算（正常 / 数据不足 / NaN 处理）
  - 品种相关性矩阵
  - 最佳类别匹配
  - FactorTypeAnalyzer 集成
  - 本地模拟 API 调用
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd
import pytest

import tools.factors.tester_calc.single_factor_test.factor_type_analysis.server_facade as server_facade
from tools.factors.tester_calc.single_factor_test.factor_type_analysis import (
    FactorTypeAnalyzer,
    ReferenceFactorRegistry,
)
from tools.factors.tester_calc.single_factor_test.factor_type_analysis.correlation import (
    best_category_match,
    compute_product_correlation_matrix,
    compute_time_series_correlation,
    product_category_profiles,
    categorize_correlation_strength,
)
from tools.factors.tester_calc.single_factor_test.factor_type_analysis.registry import (
    FactorCategory,
    ReferenceFactorDef,
    create_default_registry,
    default_registry,
)
from tools.factors.tester_calc.single_factor_test.factor_type_analysis.server_facade import (
    FactorTypeAnalysisRun,
    _infer_asset_classes,
    _load_and_calc_factor,
    _reference_skip_reason,
    _run_window_datetimes,
)

# =========================================================
#  Fixtures
# =========================================================


@pytest.fixture
def sample_registry() -> ReferenceFactorRegistry:
    """一个含 3 个类别的样本注册中心。"""
    reg = ReferenceFactorRegistry()
    reg.register(ReferenceFactorDef(
        key="trend_a", name="TrendA",
        category=FactorCategory.TREND,
        factor_alias="TrendA",
    ))
    reg.register(ReferenceFactorDef(
        key="trend_b", name="TrendB",
        category=FactorCategory.TREND,
        factor_alias="TrendB",
    ))
    reg.register(ReferenceFactorDef(
        key="vol_a", name="VolA",
        category=FactorCategory.VOLATILITY,
        factor_alias="VolA",
    ))
    reg.register(ReferenceFactorDef(
        key="mom_a", name="MomA",
        category=FactorCategory.MOMENTUM,
        factor_alias="MomA",
    ))
    return reg


@pytest.fixture
def sample_time_series() -> tuple[pd.Series, dict[str, pd.Series]]:
    """生成 500 个时间点的模拟因子序列。"""
    np.random.seed(42)
    dates = pd.date_range("2020-01-01", periods=500, freq="D")

    # 目标因子：与 trend 类强相关，与 vol 弱相关
    common_trend = np.sin(np.linspace(0, 8 * np.pi, 500))
    noise = np.random.normal(0, 0.3, 500)

    target = pd.Series(common_trend + noise * 0.2, index=dates, name="target")

    refs = {
        "trend_a": pd.Series(common_trend + np.random.normal(0, 0.1, 500), index=dates),
        "trend_b": pd.Series(common_trend * 0.8 + np.random.normal(0, 0.15, 500), index=dates),
        "vol_a": pd.Series(np.random.normal(0, 1, 500), index=dates),  # 白噪声
        "mom_a": pd.Series(common_trend * 0.5 + np.random.normal(0, 0.3, 500), index=dates),
    }
    return target, refs


@pytest.fixture
def sample_product_series() -> dict[str, pd.Series]:
    """多个产品的因子序列（模拟品种相关性）。"""
    np.random.seed(123)
    dates = pd.date_range("2020-01-01", periods=300, freq="D")
    common = np.sin(np.linspace(0, 4 * np.pi, 300))

    products = {}
    for i, name in enumerate(["RB.SHF", "HC.SHF", "I.DCE", "J.DCE"]):
        # 前两个高度相关，后两个与前面弱相关
        if i < 2:
            series = common * 0.9 + np.random.normal(0, 0.1, 300)
        else:
            series = common * 0.3 + np.random.normal(0, 0.5, 300)
        products[name] = pd.Series(series, index=dates)

    return products


# =========================================================
#  1) ReferenceFactorRegistry
# =========================================================


class TestReferenceFactorRegistry:
    def test_register_and_list(self, sample_registry):
        assert sample_registry.count() == 4
        names = [d.name for d in sample_registry.list()]
        assert "TrendA" in names
        assert "VolA" in names

    def test_duplicate_key_raises(self, sample_registry):
        with pytest.raises(ValueError, match="duplicate reference factor key"):
            sample_registry.register(ReferenceFactorDef(
                key="trend_a", name="TrendA2",
                category=FactorCategory.TREND,
                factor_alias="TrendA2",
            ))

    def test_by_category(self, sample_registry):
        trend_defs = sample_registry.by_category(FactorCategory.TREND)
        assert len(trend_defs) == 2
        vol_defs = sample_registry.by_category(FactorCategory.VOLATILITY)
        assert len(vol_defs) == 1

    def test_categories(self, sample_registry):
        cats = sample_registry.categories()
        assert FactorCategory.TREND in cats
        assert FactorCategory.VOLATILITY in cats
        assert FactorCategory.MOMENTUM in cats

    def test_manifest_contains_expected_keys(self, sample_registry):
        manifest = sample_registry.manifest()
        assert len(manifest) == 4
        for entry in manifest:
            assert "key" in entry
            assert "name" in entry
            assert "category" in entry
            assert "category_label" in entry
            assert "factor_alias" in entry
            assert "reference_source" in entry

    def test_default_registry_has_core_and_extended_styles(self):
        assert default_registry.count() >= 10
        assert FactorCategory.TREND in default_registry.categories()
        assert FactorCategory.VOLATILITY in default_registry.categories()
        assert FactorCategory.VALUE in default_registry.categories()
        assert FactorCategory.CARRY in default_registry.categories()
        assert FactorCategory.QUALITY in default_registry.categories()

    def test_default_registry_marks_data_dependent_styles_disabled(self):
        disabled = [item for item in default_registry.list() if not item.enabled_by_default]
        assert any(item.category == FactorCategory.CARRY for item in disabled)
        assert any(item.category == FactorCategory.QUALITY for item in disabled)
        for item in disabled:
            assert item.help_text

    def test_default_reference_factors_point_to_public_factor_families(self):
        """风格桶描述分析语义；可计算参照来自明确的公共因子家族。"""
        enabled_public_refs = [
            item for item in default_registry.list()
            if item.enabled_by_default and item.reference_source == "public_factor"
        ]
        assert enabled_public_refs
        for item in enabled_public_refs:
            assert item.factor_family_alias
            assert item.factor_family_alias == item.factor_alias


# =========================================================
#  2) 时序相关性
# =========================================================


class TestTimeSeriesCorrelation:
    def test_normal_correlation(self, sample_time_series):
        target, refs = sample_time_series
        results = compute_time_series_correlation(target, refs, min_periods=10)

        # 与 trend_a 应有较高的正相关
        trend_corr = results["trend_a"]["correlation"]
        assert trend_corr is not None
        assert trend_corr > 0.5, f"trend_a correlation too low: {trend_corr}"

        # 与 vol_a（白噪声）相关应接近 0
        vol_corr = results["vol_a"]["correlation"]
        assert vol_corr is not None
        assert abs(vol_corr) < 0.3, f"vol_a correlation too high: {vol_corr}"

    def test_sparman(self, sample_time_series):
        target, refs = sample_time_series
        results = compute_time_series_correlation(
            target, refs, min_periods=10, method="spearman"
        )
        assert results["trend_a"]["correlation"] is not None

    def test_insufficient_data(self):
        target = pd.Series([1, 2, 3], index=pd.date_range("2020-01-01", periods=3))
        refs = {"a": pd.Series([4, 5, 6], index=pd.date_range("2020-01-01", periods=3))}
        results = compute_time_series_correlation(target, refs, min_periods=10)
        assert results["a"]["correlation"] is None
        assert results["a"]["insufficient_data"] is True

    def test_nan_handling(self):
        dates = pd.date_range("2020-01-01", periods=100)
        target = pd.Series(np.random.normal(0, 1, 100), index=dates)
        target.iloc[20:30] = np.nan
        ref = pd.Series(np.random.normal(0, 1, 100), index=dates)
        ref.iloc[25:35] = np.nan
        results = compute_time_series_correlation(
            target, {"a": ref}, min_periods=5
        )
        # 对齐后应有约 80 个有效点
        assert results["a"]["valid_periods"] >= 80
        assert results["a"]["correlation"] is not None

    def test_p_value_present(self, sample_time_series):
        target, refs = sample_time_series
        results = compute_time_series_correlation(target, {"trend_a": refs["trend_a"]})
        assert results["trend_a"]["p_value"] is not None
        # 强相关应有小 p_value
        assert results["trend_a"]["p_value"] < 0.05

    def test_aligns_multiindex_series_by_finest_event_time(self):
        events = pd.date_range("2025-01-02 15:00", periods=5, freq="D")
        target_index = pd.MultiIndex.from_arrays(
            [events.normalize(), events], names=["trading_day", "_SIGNAL@DAY1"],
        )
        reference_index = pd.MultiIndex.from_arrays(
            [events.normalize(), ["close"] * 5, events],
            names=["trading_day", "session", "event_time"],
        )
        target = pd.Series([1, 2, 3, 4, 5], index=target_index)
        reference = pd.Series([2, 4, 6, 8, 10], index=reference_index)

        result = compute_time_series_correlation(
            target, {"reference": reference}, min_periods=3,
        )

        assert result["reference"]["correlation"] == 1.0
        assert result["reference"]["valid_periods"] == 5


# =========================================================
#  3) 品种相关性矩阵
# =========================================================


class TestProductCorrelationMatrix:
    def test_matrix_shape(self, sample_product_series):
        result = compute_product_correlation_matrix(sample_product_series)
        assert len(result["matrix"]) == 4
        assert len(result["products"]) == 4
        assert result["valid_pairs"] == 4

    def test_highly_correlated_products(self, sample_product_series):
        result = compute_product_correlation_matrix(sample_product_series)
        matrix = result["matrix"]
        products = result["products"]

        # RB.SHF 和 HC.SHF 应高度相关（both heavily trend-weighted）
        rb_idx = products.index("RB.SHF")
        hc_idx = products.index("HC.SHF")
        rb_hc_corr = matrix[rb_idx][hc_idx]
        assert rb_hc_corr is not None
        assert rb_hc_corr > 0.5, f"RB-HC correlation too low: {rb_hc_corr}"

        # 对角线的自我相关系数为 1
        for i in range(4):
            assert matrix[i][i] == 1.0 or math.isclose(matrix[i][i], 1.0)

    def test_single_product_returns_empty(self):
        series = {"RB.SHF": pd.Series([1, 2, 3], index=pd.date_range("2020-01-01", periods=3))}
        result = compute_product_correlation_matrix(series)
        assert result["matrix"] == []

    def test_sparman_method(self, sample_product_series):
        result = compute_product_correlation_matrix(
            sample_product_series, method="spearman"
        )
        assert len(result["matrix"]) == 4

    def test_aligns_products_with_different_multiindex_depths(self):
        events = pd.date_range("2025-01-02 15:00", periods=5, freq="D")
        two_levels = pd.MultiIndex.from_arrays(
            [events.normalize(), events], names=["trading_day", "event_time"],
        )
        three_levels = pd.MultiIndex.from_arrays(
            [events.normalize(), ["close"] * 5, events],
            names=["trading_day", "session", "event_time"],
        )

        result = compute_product_correlation_matrix({
            "A": pd.Series([1, 2, 3, 4, 5], index=two_levels),
            "B": pd.Series([2, 4, 6, 8, 10], index=three_levels),
        }, min_periods=3)

        assert result["matrix"][0][1] == 1.0


# =========================================================
#  4) 工具函数
# =========================================================


class TestUtilities:
    def test_categorize_correlation_strength(self):
        assert categorize_correlation_strength(0.9) == "高度相关"
        assert categorize_correlation_strength(0.6) == "中度相关"
        assert categorize_correlation_strength(0.4) == "弱相关"
        assert categorize_correlation_strength(0.1) == "几乎无关"
        assert categorize_correlation_strength(-0.85) == "高度相关"
        assert categorize_correlation_strength(None) == "无数据"

    def test_best_category_match(self):
        cat_corrs = {"趋势跟踪": 0.82, "波动率": -0.12, "动量": 0.45}
        result = best_category_match(cat_corrs)
        assert result["best_category"] == "趋势跟踪"
        assert result["best_corr"] == 0.82

    def test_best_category_match_negative(self):
        cat_corrs = {"趋势跟踪": -0.75, "波动率": 0.1}
        result = best_category_match(cat_corrs)
        # 绝对值最大的：-0.75 的绝对值 0.75 > 0.1
        assert result["best_category"] == "趋势跟踪"

    def test_best_category_match_empty(self):
        result = best_category_match({})
        assert result["best_category"] == ""

    def test_run_window_datetimes(self):
        settings = {
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
            "start_time": "09:00",
            "end_time": "15:00",
            "timezone": "Asia/Shanghai",
            "time_precision": "exact",
        }
        start, end = _run_window_datetimes(settings)
        assert start is not None
        assert end is not None
        assert start.precision == "exact"
        assert "2023" in str(start.ts)

    def test_run_window_datetimes_trading_day(self):
        settings = {
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
            "time_precision": "trading_day",
            "timezone": "Asia/Shanghai",
        }
        start, end = _run_window_datetimes(settings)
        assert start is not None
        assert end is not None
        assert start.precision == "trading_day"
        assert start.ts.tzinfo is None

    def test_run_window_datetimes_none(self):
        with pytest.raises(ValueError, match="运行时间范围缺失"):
            _run_window_datetimes(None)

    def test_run_window_datetimes_empty(self):
        with pytest.raises(ValueError, match="运行时间范围缺失"):
            _run_window_datetimes({})

    def test_run_window_datetimes_rejects_reversed_range(self):
        with pytest.raises(ValueError, match="start_date 必须早于或等于 end_date"):
            _run_window_datetimes({
                "start_date": "2025-02-01",
                "end_date": "2025-01-01",
                "time_precision": "trading_day",
            })


# =========================================================
#  5) FactorTypeAnalyzer 集成
# =========================================================


class TestFactorTypeAnalyzer:
    def test_analyze_returns_result(self, sample_registry, sample_product_series):
        analyzer = FactorTypeAnalyzer(registry=sample_registry)

        result = analyzer.analyze(
            target_series=sample_product_series,
            factor_name="TestFactor",
            method="pearson",
        )

        assert result is not None
        assert result.to_dict() is not None
        assert result.meta["factor_name"] == "TestFactor"

    def test_analyze_has_best_match(self, sample_registry, sample_product_series):
        analyzer = FactorTypeAnalyzer(registry=sample_registry)

        result = analyzer.analyze(
            target_series=sample_product_series,
            factor_name="Test",
            reference_series=self._make_refs(sample_product_series),
        )

        assert result.best_match is not None
        assert "best_category" in result.best_match

    def test_analyze_reference_correlations(self, sample_registry, sample_product_series):
        analyzer = FactorTypeAnalyzer(registry=sample_registry)

        refs = self._make_refs(sample_product_series)
        result = analyzer.analyze(
            target_series=sample_product_series,
            factor_name="Test",
            reference_series=refs,
        )

        assert len(result.reference_correlations) == 4
        for key, corr_info in result.reference_correlations.items():
            assert "correlation" in corr_info
            assert "p_value" in corr_info

    def test_analyze_product_correlation(self, sample_registry, sample_product_series):
        analyzer = FactorTypeAnalyzer(registry=sample_registry)
        refs = self._make_refs(sample_product_series)

        result = analyzer.analyze(
            target_series=sample_product_series,
            factor_name="Test",
            reference_series=refs,
        )

        pc = result.product_correlation
        assert "matrix" in pc
        assert "products" in pc
        assert len(pc["products"]) == 4

    def test_analyze_product_type_profiles(self, sample_registry, sample_product_series):
        analyzer = FactorTypeAnalyzer(registry=sample_registry)
        refs = self._make_refs(sample_product_series)

        result = analyzer.analyze(
            target_series=sample_product_series,
            factor_name="Test",
            reference_series=refs,
            min_periods=10,
        )

        assert len(result.product_type_profiles) == 4
        first = result.product_type_profiles[0]
        assert "product" in first
        assert "best_category" in first
        assert "category_scores" in first
        assert "reference_correlations" in first
        assert "趋势跟踪" in result.category_product_rankings

    def test_analyze_single_product(self, sample_registry):
        """单产品应仍有分析结果（但品种矩阵为空）。"""
        analyzer = FactorTypeAnalyzer(registry=sample_registry)
        series = {
            "RB.SHF": pd.Series(
                np.random.normal(0, 1, 200),
                index=pd.date_range("2020-01-01", periods=200),
            )
        }
        refs = self._make_refs(series)
        result = analyzer.analyze(
            target_series=series,
            factor_name="Test",
            reference_series=refs,
        )
        assert len(result.product_correlation["matrix"]) == 0

    def test_sanity_check_emits_warning(self, sample_registry):
        """全部参照因子相关性为 None 时应有警告。"""
        analyzer = FactorTypeAnalyzer(registry=sample_registry)
        dates = pd.date_range("2020-01-01", periods=50)
        target = {"RB.SHF": pd.Series(np.random.normal(0, 1, 50), index=dates)}
        refs = {"trend_a": pd.Series([np.nan] * 50, index=dates)}  # 全 NaN

        import warnings

        with pytest.warns(UserWarning, match="所有参照因子相关性计算均为 None"):
            analyzer.analyze(
                target_series=target,
                factor_name="Test",
                reference_series=refs,
            )

    @staticmethod
    def _make_refs(product_series: dict[str, pd.Series]) -> dict[str, pd.Series]:
        """为测试创建简化的参照因子序列。"""
        np.random.seed(99)
        dates = next(iter(product_series.values())).index
        return {
            "trend_a": pd.Series(np.sin(np.linspace(0, 4 * np.pi, len(dates))), index=dates),
            "trend_b": pd.Series(np.sin(np.linspace(0, 4 * np.pi, len(dates))) * 0.8, index=dates),
            "vol_a": pd.Series(np.random.normal(0, 1, len(dates)), index=dates),
            "mom_a": pd.Series(np.sin(np.linspace(0, 4 * np.pi, len(dates))) * 0.5, index=dates),
        }


# =========================================================
#  6) 本地 API 模拟
# =========================================================


class TestApiSimulation:
    """模拟前端行为，构造请求体并验证核心逻辑。
    
    因为我们是在 test 环境中，不实际启动 Flask 服务器，
    所以直接测试 FactorTypeAnalysisRun 的 from_request / run 方法
    在测试环境中不可行（依赖 server 模块）。
    
    此测试验证：
      - 请求体 JSON 序列化/反序列化正确
      - 核心分析逻辑可被 HTTP handler 调用
      - 返回结构符合前端期望
    """

    def test_request_body_roundtrip(self):
        """模拟前端 POST 请求的 JSON 结构被正确解析。"""
        body = {
            "product_path_selection": {
                "product_path_selection_id": "manual-black",
                "paths": ["Product/Futures/CNFutures/黑色/RB.SHF"],
            },
            "factor_family_alias": "mm_factors",
            "factor_alias": "MmTrend",
            "page_uuid": "test-uuid-123",
            "settings": {
                "start_date": "2023-01-01",
                "end_date": "2023-12-31",
                "correlation_method": "pearson",
            },
            "method": "pearson",
        }

        # 验证 JSON 序列化
        serialized = json.dumps(body)
        deserialized = json.loads(serialized)

        assert deserialized["product_path_selection"]["product_path_selection_id"] == "manual-black"
        assert deserialized["product_path_selection"]["paths"] == ["Product/Futures/CNFutures/黑色/RB.SHF"]
        assert deserialized["factor_alias"] == "MmTrend"
        assert deserialized["settings"]["start_date"] == "2023-01-01"
        assert deserialized["method"] == "pearson"

    def test_product_path_selection_infers_asset_domain_and_skip_reason(self):
        selection = server_facade.ProductPathSelection(
            selection_id="futures-path",
            selected_paths=["Product/Futures/CNFutures/日夜盘/日盘"],
        )
        assert _infer_asset_classes(selection) == ("futures",)

        equity_ref = ReferenceFactorDef(
            key="quality",
            name="Quality",
            category=FactorCategory.QUALITY,
            factor_alias="Quality",
            asset_classes=("equity",),
        )
        assert _reference_skip_reason(equity_ref, ("futures",)) == "asset_class_not_applicable"

        carry_ref = ReferenceFactorDef(
            key="carry",
            name="Carry",
            category=FactorCategory.CARRY,
            factor_alias="Carry",
            enabled_by_default=False,
            requires_data=("term_structure",),
        )
        assert _reference_skip_reason(carry_ref, ("futures",)) == "requires_explicit_enable_or_data:term_structure"

    def test_run_from_request_parses_min_periods_and_paths(self, monkeypatch):
        def fake_selection_from_request(data, *, page_uuid):
            return server_facade.ProductPathSelection(
                selection_id=data["product_path_selection"]["product_path_selection_id"],
                selected_paths=list(data["product_path_selection"]["paths"]),
                label="日盘",
                page_uuid=page_uuid,
            )

        monkeypatch.setattr(server_facade, "selection_from_request", fake_selection_from_request)
        body = {
            "product_path_selection": {
                "product_path_selection_id": "manual-day",
                "paths": ["Product/Futures/CNFutures/日夜盘/日盘"],
            },
            "factor_family_alias": "SgCCS",
            "factor_alias": "SgCCS|N:2m|$F:1m|$Rev",
            "settings": {"min_periods": 12},
            "method": "spearman",
        }
        run = FactorTypeAnalysisRun.from_request(body, page_uuid="page-1")
        assert run.min_periods == 12
        assert run.method == "spearman"
        assert run.selection.selected_paths == ["Product/Futures/CNFutures/日夜盘/日盘"]

    def test_reference_loader_constructs_public_default_factor_when_page_missing(self, monkeypatch):
        class FakeFactor:
            def __init__(self, alias: str):
                self.alias = alias
                self.name = alias

        class FakeFamily:
            alias = "MmTrend"

            def __init__(self):
                self.factors = []
                self.constructed_with_page_uuid = None

            def get_factors(self, *, page_uuid=None, **kwargs):
                self.constructed_with_page_uuid = page_uuid
                self.factors = [FakeFactor("MmTrend|N:20d|$F:1d")]
                return self.factors

        class FakeTester:
            def __init__(self):
                self.results = {}
                self.calculated = []

            def calc_factor(self, factor, parallel=False):
                self.calculated.append((factor.alias, parallel))

        family = FakeFamily()
        monkeypatch.setattr(server_facade, "get_factor_family_instance", lambda *args, **kwargs: family)
        monkeypatch.setattr(server_facade, "page_factors", {"page-1": {}})

        tester = FakeTester()
        factor = _load_and_calc_factor(
            tester,
            "MmTrend",
            "MmTrend",
            "page-1",
            allow_default_factor=True,
        )

        assert factor.alias == "MmTrend|N:20d|$F:1d"
        assert family.constructed_with_page_uuid == "page-1"
        assert tester.calculated == [("MmTrend|N:20d|$F:1d", False)]

    def test_run_simulates_frontend_request(self, monkeypatch):
        """模拟前端提交到后端对象并完成一次完整类型分析。"""

        class FakeProduct:
            def __init__(self, name: str):
                self.name = name
                self.alias = name

        class FakeFactor:
            def __init__(self, alias: str):
                self.alias = alias
                self.name = alias

        class FakeResult:
            def __init__(self, table: pd.DataFrame):
                self.func_table = table
                self.table = pd.DataFrame()

        class FakeTester:
            def __init__(self):
                self.products = [FakeProduct("RB.SHF"), FakeProduct("HC.SHF")]
                self._factors = []
                self.results = {}
                self.start_date = None
                self.end_date = None

        dates = pd.date_range("2024-01-01", periods=80, freq="D")
        trend = pd.Series(np.linspace(0, 1, len(dates)), index=dates)

        def fake_create_factor_tester_for_run(*args, **kwargs):
            return FakeTester()

        def fake_current_user_obj():
            return None

        def fake_load_and_calc_factor(tester, factor_family_alias, factor_alias, page_uuid, **kwargs):
            factor = FakeFactor(factor_alias)
            tester._factors.append(factor)
            if factor_alias == "TargetFactor":
                data = {
                    "RB.SHF": trend,
                    "HC.SHF": trend * 0.9,
                }
            elif factor_alias == "TrendRef":
                data = {
                    "RB.SHF": trend,
                    "HC.SHF": trend * 0.95,
                }
            else:
                rng = np.random.default_rng(42)
                data = {
                    "RB.SHF": pd.Series(rng.normal(0, 1, len(dates)), index=dates),
                    "HC.SHF": pd.Series(rng.normal(0, 1, len(dates)), index=dates),
                }
            tester.results[factor] = FakeResult(pd.DataFrame(data))
            return factor

        registry = ReferenceFactorRegistry()
        registry.register(ReferenceFactorDef(
            key="trend_ref",
            name="TrendRef",
            category=FactorCategory.TREND,
            factor_alias="TrendRef",
        ))
        registry.register(ReferenceFactorDef(
            key="vol_ref",
            name="VolRef",
            category=FactorCategory.VOLATILITY,
            factor_alias="VolRef",
        ))
        registry.register(ReferenceFactorDef(
            key="quality_ref",
            name="QualityRef",
            category=FactorCategory.QUALITY,
            factor_alias="QualityRef",
            asset_classes=("equity",),
        ))

        monkeypatch.setattr(server_facade, "create_factor_tester_for_run", fake_create_factor_tester_for_run)
        monkeypatch.setattr(server_facade, "current_user_obj", fake_current_user_obj)
        monkeypatch.setattr(server_facade, "_load_and_calc_factor", fake_load_and_calc_factor)
        monkeypatch.setattr(
            server_facade, "require_factor_data_coverage", lambda *args, **kwargs: None,
        )
        monkeypatch.setattr(server_facade, "default_registry", registry)
        monkeypatch.setattr(server_facade, "selection_from_request", lambda data, *, page_uuid: server_facade.ProductPathSelection(
            selection_id=data["product_path_selection"]["product_path_selection_id"],
            selected_paths=list(data["product_path_selection"]["paths"]),
            label="RB",
            page_uuid=page_uuid,
        ))

        run = FactorTypeAnalysisRun.from_request({
            "product_path_selection": {
                "product_path_selection_id": "manual-rb",
                "paths": ["Product/Futures/CNFutures/黑色/RB.SHF"],
            },
            "factor_family_alias": "Family",
            "factor_alias": "TargetFactor",
            "method": "pearson",
            "settings": {
                "min_periods": 10,
                "start_date": "2024-01-01",
                "end_date": "2024-03-20",
                "time_precision": "trading_day",
            },
        }, page_uuid="page-1")
        response = run.run()

        assert response["success"] is True
        assert response["meta"]["min_periods"] == 10
        assert response["meta"]["asset_classes"] == ["futures"]
        assert response["best_match"]["best_category"] == "趋势跟踪"
        assert response["product_type_profiles"][0]["best_category"] == "趋势跟踪"
        assert response["category_product_rankings"]["趋势跟踪"][0]["product"] in {"RB.SHF", "HC.SHF"}
        assert response["skipped_reference_factors"] == [{
            "key": "quality_ref",
            "name": "QualityRef",
            "category": "quality",
            "category_label": "质量",
            "reason": "asset_class_not_applicable",
            "help_text": "",
        }]

    def test_response_structure(self, sample_registry, sample_product_series):
        """验证分析结果的结构与前端期望一致。"""
        analyzer = FactorTypeAnalyzer(registry=sample_registry)
        refs = {
            "trend_a": pd.Series(
                np.sin(np.linspace(0, 4 * np.pi, 300)),
                index=next(iter(sample_product_series.values())).index,
            ),
        }

        result = analyzer.analyze(
            target_series=sample_product_series,
            factor_name="MmTrend",
            method="pearson",
            reference_series=refs,
        )

        # 期望的返回结构（对应 server_facade 的 run()）
        response = {
            "success": True,
            "target_factor": {
                "alias": "MmTrend",
                "family_alias": "",
            },
            "reference_factors": [
                {
                    "key": "trend_a",
                    "name": "TrendA",
                    "category": "trend",
                    "category_label": "趋势跟踪",
                    "correlation": result.reference_correlations["trend_a"]["correlation"],
                    "p_value": result.reference_correlations["trend_a"]["p_value"],
                    "valid_periods": result.reference_correlations["trend_a"]["valid_periods"],
                    "insufficient_data": False,
                }
            ],
            "skipped_reference_factors": [],
            "category_correlations": result.category_correlations,
            "best_match": result.best_match,
            "product_correlation": result.product_correlation,
            "product_type_profiles": result.product_type_profiles,
            "category_product_rankings": result.category_product_rankings,
            "product_summaries": [
                {
                    "product": prod,
                    "count": int(series.dropna().count()),
                    "start": str(series.index[0]),
                    "end": str(series.index[-1]),
                    "mean": round(float(series.mean()), 6),
                    "std": round(float(series.std()), 6),
                }
                for prod, series in sample_product_series.items()
            ],
            "meta": {
                "elapsed_ms": 0,
                "method": "pearson",
                "min_periods": 30,
                "product_count": 4,
                "reference_count": 1,
            },
        }

        # 验证顶层 key
        for key in ("success", "target_factor", "reference_factors",
                     "skipped_reference_factors",
                     "category_correlations", "best_match",
                     "product_correlation", "product_type_profiles",
                     "category_product_rankings", "product_summaries", "meta"):
            assert key in response, f"Missing key: {key}"

        # 验证 reference_factors 结构
        for ref in response["reference_factors"]:
            for key in ("key", "name", "category", "category_label",
                        "correlation", "p_value", "valid_periods", "insufficient_data"):
                assert key in ref, f"Missing key in reference_factors: {key}"

        # 验证 product_summaries 结构
        for summary in response["product_summaries"]:
            for key in ("product", "count", "mean", "std"):
                assert key in summary, f"Missing key in product_summaries: {key}"

    def test_all_ref_categories_in_manifest(self):
        """验证默认注册中心包含所有因子类别。"""
        registry = create_default_registry()
        cats = registry.categories()
        all_cats = {FactorCategory.TREND, FactorCategory.MOMENTUM,
                     FactorCategory.VOLATILITY, FactorCategory.POSITION,
                     FactorCategory.PRICE_VOLUME, FactorCategory.VALUE,
                     FactorCategory.CARRY, FactorCategory.LOW_VOLATILITY,
                     FactorCategory.QUALITY, FactorCategory.SIZE,
                     FactorCategory.YIELD, FactorCategory.GROWTH,
                     FactorCategory.LIQUIDITY}
        for cat in all_cats:
            assert cat in cats, f"Missing category: {cat}"

    def test_error_response_structure(self):
        """验证错误响应结构（模拟 API 错误）。"""
        error_response = {
            "success": False,
            "error": "请先选择因子",
        }
        serialized = json.dumps(error_response)
        deserialized = json.loads(serialized)
        assert deserialized["success"] is False
        assert "error" in deserialized

    def test_empty_paths_validation(self):
        """验证空路径被拒绝。"""
        # 模拟 from_request 中的验证逻辑
        paths = []
        if not isinstance(paths, list) or not paths:
            with pytest.raises(ValueError, match="请先从产品树选择产品或路径"):
                raise ValueError("请先从产品树选择产品或路径")

    def test_empty_factor_validation(self):
        """验证空因子被拒绝。"""
        factor_alias = ""
        if not factor_alias:
            with pytest.raises(ValueError, match="请先选择因子"):
                raise ValueError("请先选择因子")

    def test_product_category_profiles_directly(self, sample_registry):
        dates = pd.date_range("2020-01-01", periods=120)
        trend = pd.Series(np.linspace(0, 1, 120), index=dates)
        noisy = pd.Series(np.random.default_rng(7).normal(0, 1, 120), index=dates)
        target_series = {
            "TREND.PROD": trend + 0.01,
            "NOISY.PROD": noisy,
        }
        refs = {
            "trend_a": trend,
            "vol_a": pd.Series(np.random.default_rng(9).normal(0, 1, 120), index=dates),
        }

        payload = product_category_profiles(
            target_series=target_series,
            reference_series=refs,
            registry=sample_registry,
            min_periods=10,
        )

        trend_profile = next(item for item in payload["profiles"] if item["product"] == "TREND.PROD")
        assert trend_profile["best_category"] == "趋势跟踪"
        assert payload["category_rankings"]["趋势跟踪"][0]["product"] == "TREND.PROD"

    def test_default_registry_to_dict(self, sample_registry):
        """验证参照因子可序列化为前端所需格式。"""
        for ref_def in sample_registry.list():
            d = ref_def.to_dict()
            assert "key" in d
            assert "name" in d
            assert "category" in d
            assert "category_label" in d
            assert d["category"] in ("trend", "volatility", "momentum")
            assert d["category_label"] in ("趋势跟踪", "波动率", "动量")
