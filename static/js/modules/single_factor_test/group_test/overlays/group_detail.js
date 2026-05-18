/**
 * Group detail overlay helpers.
 *
 * In the modularized world, overlay should focus on deep-dive content.
 * Common metrics are extracted and delegated to the outer summary table.
 */
(function() {
    var GT = window.GroupTest;
    if (!GT) throw new Error('GroupTest bootstrap not loaded');

    GT.overlays = GT.overlays || {};

    function extractCommonMetrics(detail) {
        var summary = (detail && detail.summary) || {};
        return {
            'Total Return': summary['Total Return'],
            'Annual Return': summary['Annual Return'],
            'Volatility': summary['Volatility'],
            'Sharpe Ratio': summary['Sharpe Ratio'],
            'Max Drawdown': summary['Max Drawdown'],
            'Calmar Ratio': summary['Calmar Ratio'],
            'Win Rate': summary['Win Rate'],
            'Mean Return': summary['Mean Return'],
            'Skewness': summary['Skewness'],
            'Kurtosis': summary['Kurtosis'],
            'Avg Turnover': summary['Avg Turnover'],
            'Avg Turnover Accel': summary['Avg Turnover Accel'],
            'Avg Position Changes': summary['Avg Position Changes'],
            'Up Ratio': summary['Up Ratio'],
        };
    }

    GT.overlays.groupDetail = {
        extractCommonMetrics: extractCommonMetrics,
    };
})();

