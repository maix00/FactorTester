import XCTest
@testable import FTClient

final class ResearchFactorSetMemberListTests: XCTestCase {
    func testMemberPageAlwaysUsesNativeCLIAndFrozenTarget() {
        let target = "factor-set:v1:profile-maxa:path:id:rev:blob"
        XCTAssertEqual(
            ResearchFactorSetMemberList.commandArguments(
                targetRef: target, offset: 50, limit: 50
            ),
            [
                "client", "profile", "factor-worktree", "factor-set",
                "members", "--target-ref", target,
                "--offset", "50", "--limit", "50", "--json",
            ]
        )
    }
}
