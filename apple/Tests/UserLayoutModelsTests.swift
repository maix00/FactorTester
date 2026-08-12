import XCTest
@testable import FTClient

final class UserLayoutModelsTests: XCTestCase {
    func testCanonicalWorkspaceDecodesActiveUnifiedPath() {
        let value = PersonalCanonicalWorkspace(json: [
            "path": "/users/maxa/personal-workspace/factor-library",
            "owner_ref": "maxa",
            "canonical_repo_ref": "local-factor-git://abc",
        ])

        XCTAssertEqual(
            value.path,
            "/users/maxa/personal-workspace/factor-library"
        )
        XCTAssertEqual(value.ownerRef, "maxa")
        XCTAssertEqual(value.repositoryRef, "local-factor-git://abc")
    }
}
