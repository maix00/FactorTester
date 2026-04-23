/**
 * 日期处理通用函数（供 time_range_module 和 group_test_module 共用）
 */
(function() {
    if (window.DateUtils) return; // 避免重复加载

    var pad = function(n) {
        n = parseInt(n);
        return n < 10 ? '0' + n : n.toString();
    };

    var getMaxDay = function(year, month) {
        year = parseInt(year);
        month = parseInt(month);
        if (isNaN(year) || isNaN(month) || month < 1 || month > 12) return 31;
        return new Date(year, month, 0).getDate();
    };

    var carryOver = function(thisId, thisMin, thisMax, lastId, prefix) {
        var thisElem = document.getElementById(thisId);
        var lastElem = document.getElementById(lastId);
        if (!thisElem || !lastElem) return;
        var thisNum = parseInt(thisElem.value);
        var lastNum = parseInt(lastElem.value);

        if (isNaN(thisNum)) {
            thisElem.value = pad(thisMin);
            return;
        }
        if (isNaN(lastNum)) {
            lastElem.value = pad(thisMin);
            if (thisNum < thisMin) thisElem.value = pad(thisMin);
            else if (thisNum > thisMax) thisElem.value = pad(thisMax);
            else thisElem.value = pad(thisNum);
            return;
        }
        if (thisNum === thisMin - 1) {
            lastElem.value = pad(lastNum - 1);
            if (thisId.endsWith('day')) {
                thisElem.value = pad(1);
                adjustTime(lastId, prefix);
                var newMonth = parseInt(document.getElementById(prefix + '_month').value);
                var newYear = parseInt(document.getElementById(prefix + '_year').value);
                var maxDay = getMaxDay(newYear, newMonth);
                thisElem.value = pad(maxDay);
            } else {
                thisElem.value = pad(thisMax);
            }
            adjustTime(lastId, prefix);
            lastElem.value = pad(parseInt(lastElem.value));
            return;
        }
        if (thisNum === thisMax + 1) {
            lastElem.value = pad(lastNum + 1);
            thisElem.value = pad(thisMin);
            adjustTime(lastId, prefix);
            return;
        }
        if (thisNum > thisMax + 1) {
            thisElem.value = pad(thisMax);
            return;
        }
        if (thisNum < thisMin - 1) {
            thisElem.value = pad(thisMin);
            return;
        }
        thisElem.value = pad(thisNum);
    };

    var adjustTime = function(id, prefix) {
        var minuteId = prefix + '_minute';
        var hourId = prefix + '_hour';
        var dayId = prefix + '_day';
        var yearId = prefix + '_year';
        var monthId = prefix + '_month';

        var minuteElem = document.getElementById(minuteId);
        if (minuteElem) {
            var minuteVal = parseInt(minuteElem.value);
            if (isNaN(minuteVal) || minuteVal > 59 || minuteVal < 0) {
                carryOver(minuteId, 0, 59, hourId, prefix);
                return;
            } else {
                minuteElem.value = pad(minuteVal);
            }
        }

        var hourElem = document.getElementById(hourId);
        if (hourElem) {
            var hourVal = parseInt(hourElem.value);
            if (isNaN(hourVal) || hourVal > 23 || hourVal < 0) {
                carryOver(hourId, 0, 23, dayId, prefix);
                return;
            } else {
                hourElem.value = pad(hourVal);
            }
        }

        var dayElem = document.getElementById(dayId);
        var yearElem = document.getElementById(yearId);
        var monthElem = document.getElementById(monthId);
        if (dayElem && yearElem && monthElem) {
            var year = parseInt(yearElem.value);
            var month = parseInt(monthElem.value);
            var dayVal = parseInt(dayElem.value);
            var maxDay = getMaxDay(year, month);

            if (id.endsWith('month') && dayVal > maxDay) {
                dayElem.value = pad(maxDay);
            }

            if (isNaN(dayVal) || dayVal > maxDay || dayVal < 1) {
                carryOver(dayId, 1, maxDay, monthId, prefix);
                return;
            } else {
                dayElem.value = pad(dayVal);
            }

            if (isNaN(month) || month > 12 || month < 1) {
                carryOver(monthId, 1, 12, yearId, prefix);
                return;
            } else {
                monthElem.value = pad(month);
            }

            if (isNaN(year) || year < 1900 || year > 2100) {
                if (year < 1900) yearElem.value = '1900';
                else yearElem.value = '2100';
                return;
            } else {
                yearElem.value = pad(year);
            }
        }
    };

    window.DateUtils = {
        pad: pad,
        getMaxDay: getMaxDay,
        carryOver: carryOver,
        adjustTime: adjustTime
    };
})();
