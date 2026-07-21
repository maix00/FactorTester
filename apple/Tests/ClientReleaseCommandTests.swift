import XCTest
@testable import FTClient

final class ClientReleaseCommandTests: XCTestCase {
    func testDrainsLargeJSONResponseWithoutPipeDeadlock() async throws {
        let rows = try await ReleaseCommand.runArray(
            [
                "-c",
                "import json; print(json.dumps([{'value': 'x' * 70000}]))",
            ],
            executable: "/usr/bin/python3"
        )

        XCTAssertEqual(rows.count, 1)
        XCTAssertEqual(rows[0].string("value").count, 70_000)
    }
}
