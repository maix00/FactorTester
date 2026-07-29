#if os(macOS)
import XCTest
@testable import FTClient

final class ResearchDocumentAttributedLinkTests: XCTestCase {
    func testNativeAttributedReferenceKeepsAgentAuthoredLabel() throws {
        let rendered = ResearchInlineAttributedString.make(
            "[Agent 标签](factortester://evidence/evidence%3Aone)",
            scope: .init(
                componentID: "entry",
                bindings: [
                    .init(
                        id: "binding",
                        componentID: "entry",
                        kind: "evidence",
                        targetRef: "evidence:one",
                        label: "服务端标签",
                        detailFields: []
                    ),
                ]
            )
        )
        let range = (rendered.string as NSString).range(of: "Agent 标签")
        XCTAssertNotEqual(range.location, NSNotFound)
        XCTAssertEqual(
            rendered.attribute(
                ResearchDocumentReferenceTextAttribute.label,
                at: range.location,
                effectiveRange: nil
            ) as? String,
            "Agent 标签"
        )
        let url = try XCTUnwrap(URL(
            string: "factortester://evidence/evidence%3Aone"
        ))
        XCTAssertEqual(
            ResearchDocumentTypedLinkParser.reference(
                from: url,
                preservingLabelIn:
                    "[Agent 标签](factortester://evidence/evidence%3Aone)"
            )?.label,
            "Agent 标签"
        )
    }
}
#endif
