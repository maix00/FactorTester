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

    func testParsesTypedTableComponentInsteadOfDisplayingItsJSON() {
        let component = ResearchDocumentParser.parseComponent([
            "component_id": "candidate-register",
            "kind": "table",
            "title": "候选因子定义审计",
            "content": [
                "columns": ["候选", "公式"],
                "rows": [["TrMomentum", "CLOSE / CLOSE.shift(N) - 1"]],
            ],
        ])

        guard let component,
              case let .table(columns, rows, source) = component.content else {
            return XCTFail("typed table content must use the table renderer")
        }
        XCTAssertEqual(columns, ["候选", "公式"])
        XCTAssertEqual(rows, [["TrMomentum", "CLOSE / CLOSE.shift(N) - 1"]])
        XCTAssertNil(source)
    }

    func testKeepsFormulaAndCodeVerticalBarsInsideMarkdownTableCells() {
        let blocks = ResearchDocumentParser.textBlocks("""
        | 指标 | 定义 |
        | --- | --- |
        | 范数 | \\(a|b\\) |
        | 掩码 | `left | right` |
        """)

        guard case let .table(columns, rows) = blocks.first else {
            return XCTFail("formula table must remain a typed table")
        }
        XCTAssertEqual(columns, ["指标", "定义"])
        XCTAssertEqual(rows, [["范数", #"\(a|b\)"#], ["掩码", "`left | right`"]])
    }

    func testInlineCodeUsesMonospacedBackgroundStyle() {
        let value = ResearchDocumentInlineTextStyle.markdown(
            "公式使用 `SgCPSVol` 版本"
        )
        let codeRun = value.runs.first {
            $0.inlinePresentationIntent?.contains(.code) == true
        }

        XCTAssertNotNil(codeRun)
        XCTAssertNotNil(codeRun?.backgroundColor)
        XCTAssertNotNil(codeRun?.font)
    }

    func testBindingPresentationUsesTypeIconAndDescription() {
        let evidence = ResearchDocumentBinding(
            id: "evidence-1", componentID: "component-1", kind: "evidence",
            targetRef: "evidence:backtest-1", label: "回测统计证据"
        )
        let fallback = ResearchDocumentBinding(
            id: "job-1", componentID: "component-1", kind: "job",
            targetRef: "job:one", label: ""
        )

        XCTAssertEqual(
            ResearchDocumentBindingPresentation.label(for: evidence), "回测统计证据"
        )
        XCTAssertEqual(
            ResearchDocumentBindingPresentation.symbol(for: evidence),
            "doc.text.magnifyingglass"
        )
        XCTAssertEqual(ResearchDocumentBindingPresentation.label(for: fallback), "测试任务")
        XCTAssertEqual(ResearchDocumentBindingPresentation.symbol(for: fallback), "checklist")
    }

    func testUnknownGraphNodeKeepsItsRegisteredName() {
        XCTAssertEqual(ResearchDisplayText.node("custom_review"), "custom review")
    }
}
