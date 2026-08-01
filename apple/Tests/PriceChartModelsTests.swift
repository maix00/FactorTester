import Foundation
import XCTest
@testable import FTClient

final class PriceChartModelsTests: XCTestCase {
    func testDecoderFindsNestedOHLCVRowsAndNormalizesMilliseconds() throws {
        let value: [String: Any] = [
            "result": [
                "bars": [
                    ["timestamp": 1_700_000_000_000, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 25],
                    ["timestamp": 1_700_000_060_000, "open": 11, "high": 13, "low": 10, "close": 10, "volume": 30],
                ],
            ],
        ]
        let data = try JSONSerialization.data(withJSONObject: value)
        let bars = PriceBarDecoder.decodeJSON(data)

        XCTAssertEqual(bars.count, 2)
        XCTAssertEqual(bars[0].close, 11)
        XCTAssertEqual(bars[1].volume, 30)
        XCTAssertEqual(bars[0].timestamp.timeIntervalSince1970, 1_700_000_000, accuracy: 0.001)
    }

    func testDecoderRejectsRowsThatCannotRepresentACandle() throws {
        let data = try JSONSerialization.data(withJSONObject: ["rows": [["open": 1, "close": 2]]])
        XCTAssertTrue(PriceBarDecoder.decodeJSON(data).isEmpty)
    }

    func testDecoderRejectsInputAboveByteCapacityBeforeParsing() {
        let limits = PriceBarDecoder.Limits(
            maximumInputByteCount: 4,
            maximumRowCount: 10
        )

        XCTAssertThrowsError(
            try PriceBarDecoder.decodeJSON(Data("12345".utf8), limits: limits)
        ) { error in
            XCTAssertEqual(
                error as? PriceBarDecodingError,
                .inputTooLarge(maximumByteCount: 4)
            )
        }
    }

    func testDecoderRejectsOHLCVArrayAboveRowCapacity() throws {
        let data = try JSONSerialization.data(withJSONObject: [
            "bars": [row(0), row(1), row(2)],
        ])
        let limits = PriceBarDecoder.Limits(
            maximumInputByteCount: data.count,
            maximumRowCount: 2
        )

        XCTAssertThrowsError(
            try PriceBarDecoder.decodeJSON(data, limits: limits)
        ) { error in
            XCTAssertEqual(
                error as? PriceBarDecodingError,
                .rowLimitExceeded(maximumRowCount: 2)
            )
        }
    }

    func testBackgroundDecoderProducesSortedBars() async throws {
        let data = try JSONSerialization.data(withJSONObject: [
            "bars": [row(2), row(0), row(1)],
        ])

        let bars = try await PriceBarDecoder.decodeJSONInBackground(data)

        XCTAssertEqual(bars.map(\.timestamp.timeIntervalSince1970), [0, 60, 120])
        XCTAssertEqual(bars.map(\.id), [0, 1, 2])
    }

    func testDecoderCooperativelyStopsBeforeWorkWhenTaskIsCancelled() async {
        let started = expectation(description: "worker started")
        let gate = PriceChartTestGate()
        let data = try? JSONSerialization.data(withJSONObject: ["bars": [row(0)]])
        let task = Task.detached { () throws -> [PriceBar] in
            started.fulfill()
            await gate.wait()
            return try PriceBarDecoder.decodeJSON(
                data ?? Data(),
                limits: .production
            )
        }
        await fulfillment(of: [started], timeout: 1)

        task.cancel()
        await gate.open()

        do {
            _ = try await task.value
            XCTFail("Expected cancellation")
        } catch is CancellationError {
            // Expected: decodeJSON checks cancellation before JSON parsing.
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testPixelBudgetIsBoundedAndDeterministic() {
        XCTAssertEqual(PriceBarViewportSampler.barBudget(pixelWidth: 2), 1)
        XCTAssertEqual(PriceBarViewportSampler.barBudget(pixelWidth: 300), 100)
        XCTAssertEqual(
            PriceBarViewportSampler.barBudget(pixelWidth: 100_000),
            PriceBarViewportSampler.maximumRenderedBarCount
        )
    }

    func testSamplerPreservesOHLCVSemanticsPerBucket() throws {
        let bars = (0..<6).map(bar)

        let sampled = try PriceBarViewportSampler.sample(
            bars,
            maximumBarCount: 2
        )

        XCTAssertEqual(sampled.count, 2)
        XCTAssertEqual(sampled[0].id, bars[0].id)
        XCTAssertEqual(sampled[0].timestamp, bars[0].timestamp)
        XCTAssertEqual(sampled[0].open, bars[0].open)
        XCTAssertEqual(sampled[0].close, bars[2].close)
        XCTAssertEqual(sampled[0].high, bars[2].high)
        XCTAssertEqual(sampled[0].low, bars[0].low)
        XCTAssertEqual(sampled[0].volume, bars[0...2].reduce(0) { $0 + $1.volume })
        XCTAssertEqual(sampled[1].open, bars[3].open)
        XCTAssertEqual(sampled[1].close, bars[5].close)
    }

    func testSamplerUsesOnlyVisibleIntervalAndNeverExceedsRenderCapacity() throws {
        let bars = (0..<5_000).map(bar)
        let interval = bars[1_000].timestamp...bars[3_999].timestamp

        let first = try PriceBarViewportSampler.sample(
            bars,
            visibleInterval: interval,
            maximumBarCount: PriceBarViewportSampler.maximumRenderedBarCount
        )
        let second = try PriceBarViewportSampler.sample(
            bars,
            visibleInterval: interval,
            maximumBarCount: PriceBarViewportSampler.maximumRenderedBarCount
        )

        XCTAssertEqual(first, second)
        XCTAssertEqual(
            first.count,
            PriceBarViewportSampler.maximumRenderedBarCount
        )
        XCTAssertEqual(first.first?.id, 1_000)
        XCTAssertEqual(first.last?.close, bars[3_999].close)
        XCTAssertEqual(
            PriceBarViewportSampler.visibleBarCount(in: bars, interval: interval),
            3_000
        )
    }

    func testAnnualMinuteSeriesUsesPixelBudgetInsteadOfOneMarkSetPerBar() throws {
        let bars = (0..<100_000).map(bar)
        let budget = PriceBarViewportSampler.barBudget(pixelWidth: 820)

        let sampled = try PriceBarViewportSampler.sample(
            bars,
            maximumBarCount: budget
        )

        XCTAssertEqual(budget, 273)
        XCTAssertEqual(sampled.count, budget)
        XCTAssertEqual(sampled.first?.open, bars.first?.open)
        XCTAssertEqual(sampled.last?.close, bars.last?.close)
        XCTAssertEqual(
            sampled.reduce(0) { $0 + $1.volume },
            bars.reduce(0) { $0 + $1.volume }
        )
    }

    private func row(_ index: Int) -> [String: Any] {
        [
            "timestamp": index * 60,
            "open": index + 10,
            "high": index + 12,
            "low": index + 9,
            "close": index + 11,
            "volume": index + 1,
        ]
    }

    private func bar(_ index: Int) -> PriceBar {
        PriceBar(
            id: index,
            timestamp: Date(timeIntervalSince1970: Double(index * 60)),
            open: Double(index + 10),
            high: Double(index + 12),
            low: Double(index + 9),
            close: Double(index + 11),
            volume: Double(index + 1)
        )
    }
}

private actor PriceChartTestGate {
    private var isOpen = false
    private var continuations: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        guard !isOpen else { return }
        await withCheckedContinuation { continuation in
            continuations.append(continuation)
        }
    }

    func open() {
        isOpen = true
        let waiting = continuations
        continuations.removeAll()
        for continuation in waiting {
            continuation.resume()
        }
    }
}
