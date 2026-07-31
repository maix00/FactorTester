import XCTest
@testable import FTClient

final class ResearchBranchPickerTests: XCTestCase {
    func testPathControlUsesOneStableWidth() {
        XCTAssertEqual(ResearchBranchPicker.controlWidth, 300)
    }

    func testSingleCurrentPathRemainsVisibleAfterPhysicalGraphUpgrade() throws {
        let payload = """
        {"branch_ref":"graph-branch:v9:current","label":"continuation-v9",
         "current_node":"trial_execution","status":"running",
         "created_at":1,"updated_at":2,"detail_href":"/branch/current"}
        """
        let branch = try JSONDecoder().decode(
            ProfileResearchBranchSummary.self,
            from: Data(payload.utf8)
        )

        XCTAssertEqual(
            ResearchBranchPicker.resolvedSelection(
                branches: [branch],
                selectedBranchID: "historical-v8"
            ),
            "current"
        )
    }
}
