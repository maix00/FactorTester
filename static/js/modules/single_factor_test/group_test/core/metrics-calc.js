/**
 * core/metrics-calc.js — 指标计算纯函数
 * 
 * 从 app.js 解耦提取。纯计算函数，无 DOM 依赖。
 * 挂载到 GT.core.metricsCalc 命名空间。
 */
(function(){
    var GT = window.GroupTest;
    if (!GT) { console.warn('[GT core/metrics-calc] bootstrap missing'); return; }
    GT.core = GT.core || {};
    if (GT.core.metricsCalc) { console.warn('[GT core/metrics-calc] already loaded'); return; }

    var mc = {};

    /** 四舍五入到 8 位小数 */
    mc.roundVal = function(v) {
        if (isNaN(v) || !isFinite(v)) return null;
        return Math.round(v * 1e8) / 1e8;
    };

    /** 从时间戳序列推断年化周期数 */
    mc.inferPeriodsPerYearFromTimestamps = function(timestamps) {
        if (!timestamps || timestamps.length < 2) return 252;
        var dayCounts = {};
        timestamps.forEach(function(ts) {
            var d = new Date(ts);
            if (isNaN(d.getTime())) return;
            var key = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
            dayCounts[key] = (dayCounts[key] || 0) + 1;
        });
        var counts = Object.keys(dayCounts).map(function(key) { return dayCounts[key]; }).sort(function(a, b) { return a - b; });
        if (!counts.length) return 252;
        var median = counts[Math.floor(counts.length / 2)];
        if (median > 1) return median * 252;
        var days = Object.keys(dayCounts).sort();
        if (days.length < 2) return 252;
        var start = new Date(days[0] + 'T00:00:00');
        var end = new Date(days[days.length - 1] + 'T00:00:00');
        var businessDays = 0;
        for (var cur = new Date(start); cur <= end; cur.setDate(cur.getDate() + 1)) {
            var dow = cur.getDay();
            if (dow !== 0 && dow !== 6) businessDays++;
        }
        return businessDays > 0 ? Math.max(1, days.length / businessDays * 252) : 252;
    };

    /** 从收益率序列计算指标 */
    mc.calcMetricsFromReturns = function(returns, timestamps) {
        if (!returns || returns.length === 0) return {};
        var n = returns.length;
        var cum = 1.0;
        var cumMax = 1.0;
        var maxDD = 0.0;
        var winCount = 0;
        var sum = 0.0;
        var sumSq = 0.0;

        for (var i = 0; i < n; i++) {
            var r = returns[i];
            if (isNaN(r) || !isFinite(r)) continue;
            cum *= (1.0 + r);
            if (cum > cumMax) cumMax = cum;
            var dd = (cumMax - cum) / cumMax;
            if (dd > maxDD) maxDD = dd;
            if (r > 0) winCount++;
            sum += r;
            sumSq += r * r;
        }

        var mean = sum / n;
        var variance = (sumSq / n) - (mean * mean);
        var std = Math.sqrt(Math.max(variance, 0));
        var totalRet = (cum - 1.0) * 100;
        var annualPeriods = mc.inferPeriodsPerYearFromTimestamps(timestamps);
        var annualRet = (Math.pow(cum, annualPeriods / n) - 1) * 100;
        var vol = std * Math.sqrt(annualPeriods) * 100;
        var sharpe = std > 0 ? (mean * annualPeriods) / (std * Math.sqrt(annualPeriods)) : 0;
        var calmar = maxDD > 0 ? annualRet / (maxDD * 100) : 0;
        var winRate = (winCount / n) * 100;

        var skew = 0.0, kurt = 0.0;
        if (std > 0) {
            for (var i = 0; i < n; i++) {
                var z = (returns[i] - mean) / std;
                skew += z * z * z;
                kurt += z * z * z * z;
            }
            skew /= n;
            kurt = kurt / n - 3;
        }

        return {
            'Total Return': mc.roundVal(totalRet),
            'Annual Return': mc.roundVal(annualRet),
            'Volatility': mc.roundVal(vol),
            'Sharpe Ratio': mc.roundVal(sharpe),
            'Max Drawdown': mc.roundVal(maxDD * 100),
            'Calmar Ratio': mc.roundVal(calmar),
            'Win Rate': mc.roundVal(winRate),
            'Mean Return': mc.roundVal(mean * 100),
            'Skewness': mc.roundVal(skew),
            'Kurtosis': mc.roundVal(kurt),
        };
    };

    GT.core.metricsCalc = mc;
})();
