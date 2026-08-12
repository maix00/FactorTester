import XCTest
@testable import FTClient

final class ResearchReportSectionBridgeTests: XCTestCase {
    func testSingleWindowColdLaunchDisablesAppKitRestoration() {
        let suite = "ResearchReportSectionBridgeTests.window-restoration"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)

        AppRuntimePolicy.disableWindowRestoration(defaults: defaults)

        XCTAssertTrue(defaults.bool(
            forKey: AppRuntimePolicy.windowRestorationPreference
        ))
        defaults.removePersistentDomain(forName: suite)
    }

    func testSingleWindowDelegatesReopenToSystemWithoutCustomAction() {
        XCTAssertTrue(AppRuntimePolicy.shouldUseSystemWindowReopen(
            hasVisibleWindows: false
        ))
        XCTAssertFalse(AppRuntimePolicy.shouldUseSystemWindowReopen(
            hasVisibleWindows: true
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

    func testContentOnlyGroupDoesNotDrawASectionBridgeRail() {
        XCTAssertFalse(
            ResearchReportSectionBridgePresentation.containsSectionBridge([
                component("entry", kind: "entry"),
                component("table", kind: "table"),
            ])
        )
        XCTAssertTrue(
            ResearchReportSectionBridgePresentation.containsSectionBridge([
                component("entry", kind: "entry"),
                component("section", kind: "section"),
            ])
        )
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

    func testOrdinaryAndSpecialSectionsCanStartCollapsed() {
        let ordinary = component("ordinary", kind: "section")
        let special = component("special", kind: "special")

        XCTAssertEqual(
            ResearchReportSectionBridgePresentation.expandedIDs(
                [ordinary, special], mode: .collapsed
            ),
            []
        )
    }

    func testOrdinaryAndSpecialSectionsUseTheSameIconBearingHeaderContract() {
        XCTAssertEqual(
            ResearchReportSectionHeaderPresentation.iconName(
                specialKind: nil
            ),
            "doc.text"
        )
        XCTAssertEqual(
            ResearchReportSectionHeaderPresentation.iconName(
                specialKind: .externalReview
            ),
            ResearchReportSectionSpecialKind.externalReview.icon
        )
    }

    func testSpecialKindUsesOneComponentAndBindingResolver() {
        let gap = component(
            "gap",
            kind: "special",
            displayKind: "research_gap"
        )
        XCTAssertEqual(
            ResearchReportSectionSpecialKind.resolve(
                component: gap,
                bindings: []
            ),
            .researchGap
        )

        let legacy = component(
            "legacy-obligation-change",
            kind: "special",
            displayKind: "legacy_special"
        )
        let binding = ResearchDocumentBinding(
            id: "obligation-binding",
            componentID: legacy.id,
            kind: "obligation",
            targetRef: "obligation:one",
            label: "义务",
            detailFields: []
        )
        XCTAssertEqual(
            ResearchReportSectionSpecialKind.resolve(
                component: legacy,
                bindings: [binding]
            ),
            .obligationChange
        )
    }

    func testChapterCollapseHidesEveryFirstLevelSection() {
        let components = [
            component("ordinary", kind: "section"),
            component("special", kind: "special"),
        ]

        XCTAssertEqual(
            ResearchReportSectionBridgePresentation.expandedIDs(
                components, mode: .collapsed
            ),
            []
        )
        XCTAssertEqual(
            ResearchReportSectionBridgePresentation.expandedIDs(
                components, mode: .defaultExpanded
            ),
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
