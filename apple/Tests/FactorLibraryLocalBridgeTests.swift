import XCTest
@testable import FTClient

final class FactorLibraryLocalBridgeTests: XCTestCase {
    func testCatalogUsesSingleAggregateCLICommand() throws {
        let arguments = try FactorLibraryLocalBridgeContract.arguments(
            message: ["action": "catalog", "query": "动量"]
        )

        XCTAssertEqual(arguments, [
            "factor-library", "workspace", "factor-set",
            "local-catalog", "--query", "动量", "--json",
        ])
    }

    func testMembersUsesOnlyBoundedFrozenReferenceCommand() throws {
        let reference = "factor-set:v2:" + String(repeating: "a", count: 43)
        let arguments = try FactorLibraryLocalBridgeContract.arguments(
            message: [
                "action": "members",
                "target_ref": reference,
                "offset": -1,
                "limit": 500,
            ]
        )

        XCTAssertEqual(arguments, [
            "factor-library", "workspace", "factor-set",
            "members", "--target-ref", reference,
            "--offset", "0", "--limit", "100", "--json",
        ])
    }

    func testDescriptorUsesExactFrozenReferenceCommand() throws {
        let reference = "factor-set:v2:" + String(repeating: "b", count: 43)
        XCTAssertEqual(
            try FactorLibraryLocalBridgeContract.arguments(message: [
                "action": "descriptor", "target_ref": reference,
            ]),
            [
                "factor-library", "workspace", "factor-set",
                "descriptor", "--target-ref", reference, "--json",
            ]
        )
    }

    func testRunInputUsesExactFrozenReferenceCommand() throws {
        let reference = "factor-set:v2:" + String(repeating: "c", count: 43)
        XCTAssertEqual(
            try FactorLibraryLocalBridgeContract.arguments(message: [
                "action": "run-input", "target_ref": reference,
            ]),
            [
                "factor-library", "workspace", "factor-set",
                "run-input", "--target-ref", reference, "--json",
            ]
        )
    }

    func testFactorSetCommandsRejectLegacyReferences() {
        for action in ["members", "descriptor", "run-input"] {
            XCTAssertThrowsError(
                try FactorLibraryLocalBridgeContract.arguments(message: [
                    "action": action,
                    "target_ref": "factor-set:v1:legacy",
                ])
            )
        }
    }

    func testBridgeRejectsArbitraryAction() {
        XCTAssertThrowsError(
            try FactorLibraryLocalBridgeContract.arguments(
                message: ["action": "run", "argv": ["anything"]]
            )
        )
    }

    func testOwnerAndRevisionCommandsUseFactorWorktreeCLI() throws {
        XCTAssertEqual(
            try FactorLibraryLocalBridgeContract.arguments(
                message: ["action": "owners"]
            ),
            [
                "factor-library", "workspace", "owners", "list",
                "--json",
            ]
        )
        XCTAssertEqual(
            try FactorLibraryLocalBridgeContract.arguments(message: [
                "action": "revisions",
                "owner_ref": "profile:maxa",
                "limit": 999,
            ]),
            [
                "factor-library", "workspace", "revisions", "list",
                "--owner-ref", "profile:maxa", "--limit", "200", "--json",
            ]
        )
    }

    func testFamilyCommandFreezesOwnerAndCommit() throws {
        XCTAssertEqual(
            try FactorLibraryLocalBridgeContract.arguments(message: [
                "action": "families",
                "owner_ref": "profile:maxa",
                "git_commit": "0123456789abcdef",
            ]),
            [
                "factor-library", "workspace", "families", "list",
                "--owner-ref", "profile:maxa",
                "--git-commit", "0123456789abcdef", "--json",
            ]
        )
        XCTAssertEqual(
            try FactorLibraryLocalBridgeContract.arguments(message: [
                "action": "family",
                "owner_ref": "profile:maxa",
                "git_commit": "0123456789abcdef",
                "family": "MmRateOfChg",
            ]),
            [
                "factor-library", "workspace", "families", "describe",
                "--owner-ref", "profile:maxa",
                "--git-commit", "0123456789abcdef",
                "--family", "MmRateOfChg", "--json",
            ]
        )
    }

    func testInstantiateSerializesParametersDeterministically() throws {
        XCTAssertEqual(
            try FactorLibraryLocalBridgeContract.arguments(message: [
                "action": "instantiate",
                "owner_ref": "profile:maxa",
                "git_commit": "0123456789abcdef",
                "family": "MmRateOfChg",
                "params": ["N": "20d", "P": "CA"],
            ]),
            [
                "factor-library", "workspace", "factors", "instantiate",
                "--owner-ref", "profile:maxa",
                "--git-commit", "0123456789abcdef",
                "--family", "MmRateOfChg",
                "--params-json", "{\"N\":\"20d\",\"P\":\"CA\"}",
                "--json",
            ]
        )
    }

    func testListActionsReturnArrays() {
        XCTAssertTrue(FactorLibraryLocalBridgeContract.returnsArray(
            message: ["action": "owners"]
        ))
        XCTAssertTrue(FactorLibraryLocalBridgeContract.returnsArray(
            message: ["action": "families"]
        ))
        XCTAssertFalse(FactorLibraryLocalBridgeContract.returnsArray(
            message: ["action": "instantiate"]
        ))
    }
}
