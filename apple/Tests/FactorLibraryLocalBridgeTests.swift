import XCTest
@testable import FTClient

final class FactorLibraryLocalBridgeTests: XCTestCase {
    func testCatalogUsesSingleAggregateCLICommand() throws {
        let arguments = try FactorLibraryLocalBridgeContract.arguments(
            message: ["action": "catalog", "query": "动量"]
        )

        XCTAssertEqual(arguments, [
            "client", "profile", "factor-worktree", "factor-set",
            "local-catalog", "--query", "动量", "--json",
        ])
    }

    func testMembersUsesOnlyBoundedFrozenReferenceCommand() throws {
        let reference = "factor-set:v1:profile-maxa:a:b:c:d"
        let arguments = try FactorLibraryLocalBridgeContract.arguments(
            message: [
                "action": "members",
                "target_ref": reference,
                "offset": -1,
                "limit": 500,
            ]
        )

        XCTAssertEqual(arguments, [
            "client", "profile", "factor-worktree", "factor-set",
            "members", "--target-ref", reference,
            "--offset", "0", "--limit", "100", "--json",
        ])
    }

    func testBridgeRejectsArbitraryAction() {
        XCTAssertThrowsError(
            try FactorLibraryLocalBridgeContract.arguments(
                message: ["action": "run", "argv": ["anything"]]
            )
        )
    }
}
