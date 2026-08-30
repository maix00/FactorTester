import XCTest
@testable import FTClient

final class LocalRunBridgeTests: XCTestCase {
    func testUploadCommandUsesOnlyBoundedLocalArtifactArguments() throws {
        let arguments = try LocalRunBridgeContract.arguments(message: [
            "action": "upload",
            "local_job_id": "local-001",
            "name": "chart.png",
        ])

        XCTAssertEqual(
            Array(arguments.prefix(7)),
            [
                "client", "local-run", "upload",
                "local-001", "chart.png", "--json",
            ]
        )
    }

    func testUploadCommandRejectsPathTraversal() {
        XCTAssertThrowsError(
            try LocalRunBridgeContract.arguments(message: [
                "action": "upload",
                "local_job_id": "local-001",
                "name": "../secret.txt",
            ])
        )
    }

    func testSyncCommandUsesDurableOutbox() {
        XCTAssertEqual(
            Array(LocalRunBridgeContract.syncArguments().prefix(5)),
            ["client", "local-run", "outbox", "--sync", "--json"]
        )
    }
}
