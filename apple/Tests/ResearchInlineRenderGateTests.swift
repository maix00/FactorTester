import XCTest
@testable import FTClient

#if os(macOS)
final class ResearchInlineRenderGateTests: XCTestCase {
    func testScrollDrivenViewUpdatesReuseUnchangedInlineRendering() {
        let scope = ResearchDocumentReferenceScope(
            componentID: "component-1",
            bindings: []
        )
        let identity = ResearchInlineRenderIdentity(
            text: "unchanged report prose",
            scope: scope
        )
        let gate = ResearchInlineRenderGate()

        XCTAssertTrue(gate.admit(identity))
        XCTAssertFalse(gate.admit(identity))
        XCTAssertTrue(gate.admit(.init(
            text: "changed report prose",
            scope: scope
        )))
    }

    func testPlainResearchProseSkipsReferenceRegex() {
        XCTAssertFalse(ResearchDocumentTypedLinkParser.mayContainReference(
            "日盘与夜盘 IC 的参数和收益口径一致"
        ))
        XCTAssertTrue(ResearchDocumentTypedLinkParser.mayContainReference(
            "[证据](factortester://evidence/evidence%3Aic)"
        ))
        XCTAssertTrue(ResearchDocumentTypedLinkParser.mayContainReference(
            "assets/result.csv"
        ))
    }
}
#endif
