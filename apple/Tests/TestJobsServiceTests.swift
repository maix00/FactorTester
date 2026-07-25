import Foundation
import XCTest
@testable import FTClient

final class TestJobsServiceTests: XCTestCase {
    func testSafeJSONDataRejectsInvalidNestedValues() {
        let value: [String: Any] = [
            "timestamp": Date(),
            "object": NSObject(),
        ]

        XCTAssertNil(TestJobsService.safeJSONData(value))
    }

    func testSafeJSONDataSupportsScalarResultValues() throws {
        let data = try XCTUnwrap(
            TestJobsService.safeJSONData("historical result")
        )

        XCTAssertEqual(
            try JSONSerialization.jsonObject(
                with: data,
                options: [.fragmentsAllowed]
            ) as? String,
            "historical result"
        )
    }
}
