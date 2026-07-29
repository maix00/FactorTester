import XCTest
@testable import FTClient

final class ResearchDocumentReferenceTrustTests: XCTestCase {
    func testOnlyExactCurrentComponentBindingTrustsInternalReference() {
        let reference = ResearchDocumentTypedLink(
            kind: "evidence",
            targetRef: "evidence:one",
            label: "Agent 标签"
        )
        let trusted = scope(componentID: "entry", kind: "evidence")

        XCTAssertEqual(trusted.trusted(reference)?.componentID, "entry")
        XCTAssertNil(
            scope(componentID: "other", kind: "evidence").trusted(reference)
        )
        XCTAssertNil(scope(componentID: "entry", kind: "job").trusted(reference))
        XCTAssertNil(
            scope(
                componentID: "entry",
                kind: "evidence",
                targetRef: "evidence:two"
            ).trusted(reference)
        )
    }

    func testUnboundTypedLinkBecomesPlainAgentLabel() {
        let segments = ResearchDocumentReferenceScope(
            componentID: "entry",
            bindings: []
        ).presentationSegments(
            in: "[Agent 标签](factortester://evidence/evidence%3Aone)"
        )

        XCTAssertEqual(segments, [.text("Agent 标签")])
    }

    func testSafeWebLinkDoesNotRequireInternalBinding() {
        let reference = ResearchDocumentTypedLink(
            kind: "url",
            targetRef: "https://example.com/report",
            label: "外部文档"
        )

        XCTAssertEqual(
            ResearchDocumentReferenceScope(
                componentID: "entry",
                bindings: []
            ).trusted(reference)?.label,
            "外部文档"
        )
    }

    #if os(macOS)
    func testAppKitAttributesExistOnlyForExactBinding() {
        let source = "[Agent 标签](factortester://evidence/evidence%3Aone)"
        let plain = ResearchInlineAttributedString.make(source)
        let trusted = ResearchInlineAttributedString.make(
            source,
            scope: scope(componentID: "entry", kind: "evidence")
        )
        let plainRange = (plain.string as NSString).range(of: "Agent 标签")
        let trustedRange = (trusted.string as NSString).range(of: "Agent 标签")

        XCTAssertNil(plain.attribute(
            .link,
            at: plainRange.location,
            effectiveRange: nil
        ))
        XCTAssertNil(plain.attribute(
            ResearchDocumentReferenceTextAttribute.label,
            at: plainRange.location,
            effectiveRange: nil
        ))
        XCTAssertNotNil(trusted.attribute(
            .link,
            at: trustedRange.location,
            effectiveRange: nil
        ))
        XCTAssertEqual(
            trusted.attribute(
                ResearchDocumentReferenceTextAttribute.label,
                at: trustedRange.location,
                effectiveRange: nil
            ) as? String,
            "Agent 标签"
        )
    }
    #endif

    private func scope(
        componentID: String,
        kind: String,
        targetRef: String = "evidence:one"
    ) -> ResearchDocumentReferenceScope {
        .init(
            componentID: componentID,
            bindings: [
                .init(
                    id: "binding",
                    componentID: "entry",
                    kind: kind,
                    targetRef: targetRef,
                    label: "服务端标签",
                    detailFields: []
                ),
            ]
        )
    }
}
