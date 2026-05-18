/**
 * Metrics section definitions for GroupTest.
 *
 * The intent is to keep "what we show" separate from "how we render".
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    function buildSections() {
        // NOTE: keys are backend metric names (English) used across modules.
        return [
            {
                id: 'returns',
                title: '收益',
                metrics: ['Total Return', 'Annual Return', 'Mean Return', 'Win Rate'],
            },
            {
                id: 'risk',
                title: '风险',
                metrics: ['Volatility', 'Max Drawdown'],
            },
            {
                id: 'risk_adjusted',
                title: '风险调整后收益',
                metrics: ['Sharpe Ratio', 'Calmar Ratio'],
            },
            {
                id: 'distribution',
                title: '分布形态',
                metrics: ['Skewness', 'Kurtosis'],
            },
            {
                id: 'trading',
                title: '交易与换手',
                metrics: ['Avg Turnover', 'Avg Turnover Accel', 'Avg Position Changes', 'Up Ratio'],
            },
        ];
    }

    GT.metrics = GT.metrics || {};
    GT.metrics.sections = {
        buildSections: buildSections,
    };
})();

