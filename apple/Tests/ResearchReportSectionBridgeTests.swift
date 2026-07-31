import XCTest
@testable import FTClient

final class ResearchReportSectionBridgeTests: XCTestCase {
    func testAdjacentSpecialSectionsFormOneBridge() {
        let values = [
            component("ordinary-a", kind: "section"),
            component("special-a", kind: "special"),
            component("special-b", kind: "special"),
            component("ordinary-b", kind: "section"),
        ]

        let groups = ResearchReportChildGroup.group(values)

        XCTAssertEqual(groups.count, 3)
        XCTAssertEqual(groups[0].componentIDs, ["ordinary-a"])
        XCTAssertEqual(groups[1].componentIDs, ["special-a", "special-b"])
        XCTAssertTrue(groups[1].isSpecialBridge)
        XCTAssertEqual(groups[2].componentIDs, ["ordinary-b"])
    }

    func testOneSpecialSectionDoesNotCreateAnArtificialBridge() {
        let groups = ResearchReportChildGroup.group([
            component("special-a", kind: "special"),
            component("ordinary", kind: "entry"),
        ])

        XCTAssertEqual(groups.count, 2)
        XCTAssertFalse(groups[0].isSpecialBridge)
    }

    func testPathSelectionSeparatesSpecialBridgesAboveAndBelow() {
        let groups = ResearchReportChildGroup.group([
            component("special-a", kind: "special"),
            component("special-b", kind: "special"),
            component(
                "path-selection",
                kind: "special",
                displayKind: "path_selection"
            ),
            component("special-c", kind: "special"),
            component("special-d", kind: "special"),
        ])

        XCTAssertEqual(groups.map(\.componentIDs), [
            ["special-a", "special-b"],
            ["path-selection"],
            ["special-c", "special-d"],
        ])
        XCTAssertEqual(
            groups.map(\.isSpecialBridge),
            [true, false, true]
        )
    }

    private func component(
        _ id: String,
        kind: String,
        displayKind: String? = nil
    ) -> ResearchDocumentComponent {
        ResearchDocumentComponent(
            id: id,
            kind: kind,
            displayKind: displayKind ?? (
                kind == "special" ? "external_review" : ""
            ),
            parentID: "chapter",
            title: id,
            body: "",
            content: .none
        )
    }
}
