import XCTest
@testable import FTClient

final class ResearchDocumentTextBlockTests: XCTestCase {
    func testSeparatesFencedCodeFromProse() {
        let blocks = ResearchDocumentParser.textBlocks("""
        结论说明
        ```python
        signal = close / vwap
        ```
        后续说明
        """)

        XCTAssertEqual(blocks.count, 3)
        guard case let .code(language, source) = blocks[1] else {
            return XCTFail("fenced source must use the shared code renderer")
        }
        XCTAssertEqual(language, "python")
        XCTAssertEqual(source, "signal = close / vwap")
    }

    func testRecognizesInlineAndDisplayMath() {
        XCTAssertTrue(ResearchReportTextProjection.containsMath("收益 \\(r_t\\)"))
        XCTAssertTrue(ResearchReportTextProjection.containsMath("\\[x^2\\]"))
        XCTAssertTrue(ResearchReportTextProjection.containsMath("$$x^2$$"))
    }

    func testSeparatesDisplayMathFromRichProse() {
        let blocks = ResearchDocumentParser.textBlocks("""
        前置说明
        $$
        IR = \\frac{\\mu}{\\sigma}
        $$
        后续说明
        """)

        XCTAssertEqual(blocks.count, 3)
        guard case let .math(latex) = blocks[1] else {
            return XCTFail("display source must use the shared math renderer")
        }
        XCTAssertEqual(latex, "IR = \\frac{\\mu}{\\sigma}")
    }

    func testSeparatesNestedOrderedAndUnorderedListsFromProse() {
        let blocks = ResearchDocumentParser.textBlocks("""
        结论：
        1. 主假设
          - \\(IC_t\\) 为正
        2. 备选假设
        后续说明
        """)

        XCTAssertEqual(blocks.count, 3)
        guard case let .list(items) = blocks[1] else {
            return XCTFail("list source must use the shared list renderer")
        }
        XCTAssertEqual(items.map(\.marker), ["1.", "-", "2."])
        XCTAssertEqual(items.map(\.depth), [0, 1, 0])
    }

    func testUnknownGraphNodeKeepsItsRegisteredName() {
        XCTAssertEqual(ResearchDisplayText.node("custom_review"), "custom review")
    }
}
