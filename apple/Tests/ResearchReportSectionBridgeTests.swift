import XCTest
@testable import FTClient

final class ResearchReportSectionBridgeTests: XCTestCase {
    func testDebugWindowGroupDelegatesReopenToSystemWithoutCustomAction() {
        XCTAssertTrue(AppRuntimePolicy.shouldUseSystemWindowReopen(
            hasVisibleWindows: false,
            hasCustomAction: false
        ))
        XCTAssertFalse(AppRuntimePolicy.shouldUseSystemWindowReopen(
            hasVisibleWindows: false,
            hasCustomAction: true
        ))
        XCTAssertFalse(AppRuntimePolicy.shouldUseSystemWindowReopen(
            hasVisibleWindows: true,
            hasCustomAction: false
        ))
    }

    func testAllAdjacentSectionsFormOneBridge() {
        let values = [
            component("ordinary-a", kind: "section"),
            component("special-a", kind: "special"),
            component("special-b", kind: "special"),
            component("ordinary-b", kind: "section"),
        ]

        let groups = ResearchReportChildGroup.group(values)

        XCTAssertEqual(groups.count, 1)
        XCTAssertEqual(groups[0].componentIDs, [
            "ordinary-a", "special-a", "special-b", "ordinary-b",
        ])
    }

    func testSingleSectionStillUsesTheSharedBridgePresentation() {
        let groups = ResearchReportChildGroup.group([
            component("ordinary", kind: "entry"),
        ])

        XCTAssertEqual(groups.count, 1)
    }

    func testPathSelectionRemainsInsideContinuousBridge() {
        let groups = ResearchReportChildGroup.group([
            component("ordinary-a", kind: "section"),
            component("special-b", kind: "special"),
            component(
                "path-selection",
                kind: "special",
                displayKind: "path_selection"
            ),
            component("special-c", kind: "special"),
            component("ordinary-d", kind: "subsection"),
        ])

        XCTAssertEqual(groups.count, 1)
        XCTAssertEqual(groups[0].componentIDs, [
            "ordinary-a", "special-b", "path-selection",
            "special-c", "ordinary-d",
        ])
    }

    func testNestedChildrenUseTheSameContinuousBridge() {
        let groups = ResearchReportChildGroup.group([
            component("nested-ordinary", kind: "subsection"),
            component("nested-special", kind: "special"),
            component("nested-entry", kind: "entry"),
        ])

        XCTAssertEqual(groups.count, 1)
        XCTAssertEqual(groups[0].componentIDs, [
            "nested-ordinary", "nested-special", "nested-entry",
        ])
    }

    func testOrdinarySectionsStartExpandedAndSpecialSectionsCollapsed() {
        let ordinary = component("ordinary", kind: "section")
        let special = component("special", kind: "special")

        XCTAssertEqual(
            ResearchReportSectionBridgePresentation.initiallyExpandedIDs([
                ordinary, special,
            ]),
            ["ordinary"]
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
