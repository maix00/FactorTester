#if os(macOS)
import XCTest
@testable import FTClient

final class ResearchDocumentAttributedLinkTests: XCTestCase {
    func testFactorReferenceKeepsPurpleTextAndSpacesAssignment() {
        let rendered = ResearchInlineAttributedString.make(
            "[TrMomentum](factortester://factor/factor-family%3Av1%3Aone)=`CLOSE`",
            scope: .init(
                componentID: "entry",
                bindings: [
                    .init(
                        id: "binding",
                        componentID: "entry",
                        kind: "factor",
                        targetRef: "factor-family:v1:one",
                        label: "TrMomentum",
                        detailFields: []
                    ),
                ]
            )
        )
        let range = (rendered.string as NSString).range(of: "TrMomentum")

        XCTAssertEqual(rendered.string, "\u{fffc} TrMomentum = CLOSE")
        XCTAssertEqual(
            rendered.attribute(
                .foregroundColor,
                at: range.location,
                effectiveRange: nil
            ) as? NSColor,
            .systemPurple
        )
        XCTAssertNil(
            ResearchInlineTextView().linkTextAttributes?[.foregroundColor]
        )
    }

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

    func testHeadingAndBodyInlineCodeUseTheSameLayoutAttribute() {
        let headingFont = NSFont.systemFont(ofSize: 22, weight: .semibold)
        let rendered = ResearchInlineAttributedString.make(
            "标题中的 `CLOSE`",
            font: headingFont
        )
        let range = (rendered.string as NSString).range(of: "CLOSE")

        XCTAssertEqual(
            rendered.attribute(
                ResearchInlineCodeLayoutManager.attribute,
                at: range.location,
                effectiveRange: nil
            ) as? Bool,
            true
        )
        XCTAssertEqual(
            (rendered.attribute(
                .font,
                at: range.location,
                effectiveRange: nil
            ) as? NSFont)?.pointSize,
            headingFont.pointSize
        )
    }

    @MainActor
    func testFormulaReferenceAndEqualsShareOneNativeLineLayout() {
        let finished = expectation(description: "inline formula rendered")
        let latex = #"(P_t-P_{t-N})/mean_N(P)"#
        var formula: ResearchInlineMathRendered?
        ResearchInlineMathImageRenderer.shared.request(
            latex: latex,
            fontSize: NSFont.systemFontSize
        ) {
            formula = $0
            finished.fulfill()
        }
        wait(for: [finished], timeout: 5)
        let resolved = try? XCTUnwrap(formula)
        guard let resolved else { return }
        let key = ResearchInlineMathImageRenderer.key(
            latex: latex,
            fontSize: NSFont.systemFontSize
        )
        let scope = ResearchDocumentReferenceScope(
            componentID: "entry",
            bindings: [
                .init(
                    id: "factor",
                    componentID: "entry",
                    kind: "factor",
                    targetRef: "factor:momentum",
                    label: "MmTrend",
                    detailFields: []
                ),
            ]
        )
        let value = ResearchInlineAttributedString.make(
            "[MmTrend](factortester://factor/factor%3Amomentum)"
                + "=\\(\(latex)\\)",
            scope: scope,
            mathImages: [key: resolved]
        )

        XCTAssertEqual(value.string, "\u{fffc} MmTrend = \u{fffc}")
        let formulaIndex = value.length - 1
        let attachment = value.attribute(
            .attachment,
            at: formulaIndex,
            effectiveRange: nil
        ) as? NSTextAttachment
        XCTAssertEqual(
            -(attachment?.bounds.origin.y ?? 0),
            resolved.image.size.height - resolved.baselineFromTop,
            accuracy: 0.5
        )
        XCTAssertGreaterThan(resolved.baselineFromTop, 0)
        XCTAssertLessThan(
            resolved.baselineFromTop,
            resolved.image.size.height
        )
    }

    @MainActor
    func testSimpleFormulaMatchesNativeFontXHeightAndLineHeight() {
        let font = NSFont.preferredFont(forTextStyle: .body)
        let formula = renderFormula("x", font: font)
        guard let formula else { return }
        let key = ResearchInlineMathImageRenderer.key(
            latex: "x",
            fontSize: font.pointSize
        )
        let withFormula = ResearchInlineAttributedString.make(
            "正文 \\(x\\) 正文",
            font: font,
            mathImages: [key: formula]
        )
        let plain = NSAttributedString(
            string: "正文 x 正文",
            attributes: [.font: font]
        )

        XCTAssertEqual(
            formula.baselineFromTop,
            font.xHeight,
            accuracy: 1
        )
        XCTAssertEqual(
            lineHeight(withFormula),
            lineHeight(plain),
            accuracy: 0.5
        )
    }

    @MainActor
    func testFormulaWrapsAsOneAttachmentWithoutChangingParagraphSpacing() {
        let font = NSFont.preferredFont(forTextStyle: .body)
        let latex = #"\frac{P_t-P_{t-N}}{mean_N(P)}"#
        let formula = renderFormula(latex, font: font)
        guard let formula else { return }
        let key = ResearchInlineMathImageRenderer.key(
            latex: latex,
            fontSize: font.pointSize
        )
        let value = ResearchInlineAttributedString.make(
            "较长的前置正文 \\(\(latex)\\) 后续正文",
            font: font,
            mathImages: [key: formula]
        )
        let formulaRange = (value.string as NSString).range(of: "\u{fffc}")
        let paragraph = value.attribute(
            .paragraphStyle,
            at: formulaRange.location,
            effectiveRange: nil
        ) as? NSParagraphStyle

        XCTAssertEqual(formulaRange.length, 1)
        XCTAssertEqual(
            paragraph?.lineSpacing,
            ResearchDocumentTextMetrics.lineSpacing
        )
        XCTAssertGreaterThan(lineCount(value, width: 150), 1)
    }

    @MainActor
    private func renderFormula(
        _ latex: String,
        font: NSFont
    ) -> ResearchInlineMathRendered? {
        let finished = expectation(description: "formula \(latex) rendered")
        var result: ResearchInlineMathRendered?
        ResearchInlineMathImageRenderer.shared.request(
            latex: latex,
            fontSize: font.pointSize
        ) {
            result = $0
            finished.fulfill()
        }
        wait(for: [finished], timeout: 5)
        return result
    }

    private func lineHeight(_ value: NSAttributedString) -> CGFloat {
        usedRect(value, width: 1_000).height
    }

    private func lineCount(
        _ value: NSAttributedString,
        width: CGFloat
    ) -> Int {
        let storage = NSTextStorage(attributedString: value)
        let layout = NSLayoutManager()
        let container = NSTextContainer(
            containerSize: NSSize(width: width, height: .greatestFiniteMagnitude)
        )
        container.lineFragmentPadding = 0
        layout.addTextContainer(container)
        storage.addLayoutManager(layout)
        layout.ensureLayout(for: container)
        var count = 0
        layout.enumerateLineFragments(
            forGlyphRange: layout.glyphRange(for: container)
        ) { _, _, _, _, _ in count += 1 }
        return count
    }

    private func usedRect(
        _ value: NSAttributedString,
        width: CGFloat
    ) -> NSRect {
        let storage = NSTextStorage(attributedString: value)
        let layout = NSLayoutManager()
        let container = NSTextContainer(
            containerSize: NSSize(width: width, height: .greatestFiniteMagnitude)
        )
        container.lineFragmentPadding = 0
        layout.addTextContainer(container)
        storage.addLayoutManager(layout)
        layout.ensureLayout(for: container)
        return layout.usedRect(for: container)
    }
}
#endif
