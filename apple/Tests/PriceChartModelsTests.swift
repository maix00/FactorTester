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
}
