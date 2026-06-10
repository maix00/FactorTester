import subprocess
import textwrap
from pathlib import Path

import numpy as np

from tests._repo import repo_root

REPO_ROOT = repo_root(Path(__file__))


def test_sectioned_group_metrics_keep_backend_percent_units():
    script = textwrap.dedent(
        """
        const fs = require('fs');
        const vm = require('vm');
        const assert = require('assert');

        const code = fs.readFileSync(process.argv[1], 'utf8');
        const sandbox = {
            window: { GroupTest: { metrics: { sections: { buildSections: () => [] } } } },
            console: console,
        };

        vm.runInNewContext(code, sandbox);
        const display = sandbox.window.GroupTest.metrics.table.metricDisplay;

        assert.strictEqual(display('Total Return', 12.5), '12.50%');
        assert.strictEqual(display('Win Rate', 55), '55.00%');
        assert.strictEqual(display('Volatility', 8.1234), '8.123%');
        assert.strictEqual(display('Max Drawdown', -6.5), '-6.500%');
        assert.strictEqual(display('Mean Return', 0.03), '3.00 bp');
        assert.strictEqual(display('Avg Turnover', 0.25), '25.00%');
        """
    )
    table_js = REPO_ROOT / 'static/js/modules/single_factor_test/group_test/metrics/table.js'
    subprocess.run(['node', '-e', script, str(table_js)], check=True)


def test_group_fee_config_parses_uniform_and_closetoday_rates():
    from server.modules.single_factor_test.group import _parse_group_fee_config

    fee_uniform, fee_map, use_closetoday = _parse_group_fee_config({'fee': 0.03})
    assert fee_uniform == 0.0003
    # 模式1/2：fee_map 为空时，不加载 FeeData，返回空字典
    assert fee_map == {}
    assert use_closetoday is False

    fee_uniform, fee_map, use_closetoday = _parse_group_fee_config({
        'fee': 0,
        'use_closetoday': True,
        'fee_map': {
            'rb': {
                'open_ratio': 0.0001,
                'close_ratio': 0.0002,
                'closetoday_ratio': 0.0005,
            },
        },
    })
    assert fee_uniform == 0
    assert use_closetoday is True
    # 模式3：前端传的 fee_map 只做字段名映射，不加载 FeeData 补全
    assert fee_map == {'RB': {
        'open_rate': 0.0001,
        'open_fixed': 0.0,
        'close_rate': 0.0002,
        'close_fixed': 0.0,
        'close_today_rate': 0.0005,
        'close_today_fixed': 0.0,
        'close_yesterday_rate': 0.0002,
        'close_yesterday_fixed': 0.0,
        'multiplier': 1.0,
        'min_tick': 0.0,
        'min_trade_quantity': 1.0,
        'long_margin_ratio': 1.0,
        'short_margin_ratio': 1.0,
    }}


def test_group_detail_includes_product_fee_rates_and_actual_fee_costs():
    from tools.factors.tests.single_factor_test.group.detail import build_group_detail

    index = [np.datetime64('2025-01-01T09:00'), np.datetime64('2025-01-01T09:01')]
    detail = build_group_detail(
        group_index=0,
        products_by_group={0: {index[0]: ['RB.SHF'], index[1]: ['RB.SHF', 'CU.SHF']}},
        group_returns_np=np.array([[0.001], [0.002]]),
        index_list=index,
        product_gross_contrib_np=np.array([[[0.001, 0.0]], [[0.0015, 0.0005]]]),
        valid_cols=['RB.SHF', 'CU.SHF'],
        group_gross_returns_np=np.array([[0.001], [0.002]]),
        trade_notional_ratio_np=np.array([[1.0], [0.5]]),
        fee_costs_np=np.array([[0.0003], [0.0001]]),
        open_fee_vec=np.array([0.0001, 0.0002]),
        close_fee_vec=np.array([0.0003, 0.0004]),
        close_today_fee_vec=np.array([0.0005, 0.0006]),
    )

    first_product = detail['entry_frequency'][0]['product']
    np.testing.assert_allclose(
        [
            first_product['fee']['open'],
            first_product['fee']['close_today'],
            first_product['fee']['close_yesterday'],
            first_product['fee']['total'],
        ],
        [0.0001, 0.0005, 0.0003, 0.0004],
    )
    assert detail['top_periods'][0]['products'][0]['fee']['open'] in {0.0001, 0.0002}
    np.testing.assert_allclose(detail['tradability_analysis']['avg_actual_fee_cost'], 0.0002)
    np.testing.assert_allclose(detail['tradability_analysis']['actual_fee_per_traded_notional'], 0.0004 / 1.5)
