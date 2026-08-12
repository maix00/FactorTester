import Foundation

enum PriceBarViewportSampler {
    static let minimumCandleWidth = 3.0
    static let maximumRenderedBarCount = 1_200

    static func barBudget(pixelWidth: Double) -> Int {
        guard pixelWidth.isFinite, pixelWidth > 0 else { return 1 }
        return min(
            maximumRenderedBarCount,
            max(1, Int(pixelWidth / minimumCandleWidth))
        )
    }

    static func sampleInBackground(
        _ bars: [PriceBar],
        visibleInterval: ClosedRange<Date>? = nil,
        maximumBarCount: Int
    ) async throws -> [PriceBar] {
        let worker = Task.detached(priority: .userInitiated) {
            try sample(
                bars,
                visibleInterval: visibleInterval,
                maximumBarCount: maximumBarCount
            )
        }
        return try await withTaskCancellationHandler {
            try await worker.value
        } onCancel: {
            worker.cancel()
        }
    }

    static func sample(
        _ bars: [PriceBar],
        visibleInterval: ClosedRange<Date>? = nil,
        maximumBarCount: Int
    ) throws -> [PriceBar] {
        guard !bars.isEmpty, maximumBarCount > 0 else { return [] }
        try Task.checkCancellation()
        let visible = visibleIndices(in: bars, interval: visibleInterval)
        guard !visible.isEmpty else { return [] }
        if visible.count <= maximumBarCount {
            return Array(bars[visible])
        }

        let targetCount = min(visible.count, maximumBarCount)
        var sampled: [PriceBar] = []
        sampled.reserveCapacity(targetCount)
        for bucket in 0..<targetCount {
            try Task.checkCancellation()
            let lower = visible.lowerBound + bucket * visible.count / targetCount
            let upper = visible.lowerBound
                + (bucket + 1) * visible.count / targetCount
            let first = bars[lower]
            let last = bars[upper - 1]
            var high = first.high
            var low = first.low
            var volume = 0.0
            for index in lower..<upper {
                if index.isMultiple(of: 256) {
                    try Task.checkCancellation()
                }
                high = max(high, bars[index].high)
                low = min(low, bars[index].low)
                volume += bars[index].volume
            }
            sampled.append(PriceBar(
                id: first.id,
                timestamp: first.timestamp,
                open: first.open,
                high: high,
                low: low,
                close: last.close,
                volume: volume
            ))
        }
        return sampled
    }

    static func visibleBarCount(
        in bars: [PriceBar], interval: ClosedRange<Date>?
    ) -> Int {
        visibleIndices(in: bars, interval: interval).count
    }

    private static func visibleIndices(
        in bars: [PriceBar], interval: ClosedRange<Date>?
    ) -> Range<Int> {
        guard let interval else { return bars.indices }
        let lower = firstIndex(in: bars) { $0.timestamp >= interval.lowerBound }
        let upper = firstIndex(in: bars) { $0.timestamp > interval.upperBound }
        return lower..<upper
    }

    private static func firstIndex(
        in bars: [PriceBar], matching predicate: (PriceBar) -> Bool
    ) -> Int {
        var lower = bars.startIndex
        var upper = bars.endIndex
        while lower < upper {
            let middle = lower + (upper - lower) / 2
            if predicate(bars[middle]) {
                upper = middle
            } else {
                lower = middle + 1
            }
        }
        return lower
    }
}
