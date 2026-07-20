import XCTest
@testable import FTClient

final class UserLayoutModelsTests: XCTestCase {
    func testMigrationPlanDecodesUnifiedUserTree() {
        let plan = PersonalWorkspaceMigrationPlan(json: [
            "operation": "principal_user_layout_migration",
            "target_layout": [
                "user_root": "/users/maxa",
                "personal_workspace": "/users/maxa/personal-workspace",
                "factor_library": "/users/maxa/personal-workspace/factor-library",
                "profiles_root": "/users/maxa/profiles",
                "legacy_quarantine": "/users/maxa/legacy-quarantine",
            ],
            "canonical": [
                "source": "/legacy/factors",
                "target": "/users/maxa/personal-workspace/factor-library",
                "dirty_file_count": 3,
            ],
            "profiles": [["profile_id": "maxa-research"]],
            "worktrees": [[
                "new_path": "/users/maxa/profiles/maxa-research/factor-worktree",
            ]],
            "legacy_quarantine": [[
                "target": "/users/maxa/legacy-quarantine/old-maxa",
            ]],
            "ready": true,
        ])

        XCTAssertEqual(plan.layout.userRoot, "/users/maxa")
        XCTAssertEqual(plan.linkedProfiles, ["maxa-research"])
        XCTAssertEqual(plan.dirtyCount, 3)
        XCTAssertEqual(plan.legacyQuarantine.count, 1)
        XCTAssertTrue(plan.preservesBranches)
        XCTAssertTrue(plan.preservesUncommitted)
    }
}
