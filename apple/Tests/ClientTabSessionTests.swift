import XCTest
@testable import FTClient

final class ClientTabSessionTests: XCTestCase {
    func testResearchOpensOnResearchCatalogSection() {
        XCTAssertEqual(ClientTabSession().researchSection, .researches)
    }

    func testStoreRetainsOnlyLightweightStateForAnOpenTab() {
        let store = ClientTabSessionStore()
        let first = store.session(for: ClientTab.research.id)
        first.researchSection = .graph
        first.researchLifecycle = .archived

        let restored = store.session(for: ClientTab.research.id)

        XCTAssertTrue(first === restored)
        XCTAssertEqual(restored.researchSection, .graph)
        XCTAssertEqual(restored.researchLifecycle, .archived)
    }

    func testClosingTabDiscardsItsSession() {
        let store = ClientTabSessionStore()
        let first = store.session(for: "work-package:one")
        first.selectedBranchID = "branch-one"

        store.removeSession(for: "work-package:one")
        let reopened = store.session(for: "work-package:one")

        XCTAssertFalse(first === reopened)
        XCTAssertEqual(reopened.selectedBranchID, "")
    }

    func testRemovingTabReleasesWebPageSessionButKeepsTabState() {
        let store = ClientTabSessionStore()
        let session = store.session(for: "research-report:one")
        session.selectedBranchID = "branch-one"
        _ = session.ensureWebPageSession()

        store.activate("research-report:one")
        store.removeSession(for: "research-report:one")

        XCTAssertNil(session.webPageSession)
        XCTAssertEqual(session.selectedBranchID, "branch-one")
    }

    func testReportsKeepIndependentSelectedChaptersWithinOneTab() {
        let tab = ClientTabSession()
        let first = tab.reportSession(for: "file:///first/HEAD.json")
        first.generation = 4
        first.selectedChapterID = "chapter-four"

        let restored = tab.reportSession(for: "file:///first/HEAD.json")
        let second = tab.reportSession(for: "file:///second/HEAD.json")

        XCTAssertTrue(first === restored)
        XCTAssertEqual(restored.generation, 4)
        XCTAssertEqual(restored.selectedChapterID, "chapter-four")
        XCTAssertFalse(first === second)
        XCTAssertEqual(second.selectedChapterID, "")
    }
}
