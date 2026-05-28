import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


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
    assert fee_map == {'RB': {'open': 0.0001, 'close': 0.0005}}
    assert use_closetoday is True
