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

    func testParsesStructuredListComponentForNativeRendering() {
        let component = ResearchDocumentParser.parseComponent([
            "component_id": "constraints",
            "kind": "list",
            "title": "研究约束",
            "content": [
                "style": "ordered",
                "items": [
                    ["text": "保持样本外封存", "depth": 0],
                    ["text": "记录每个窗口", "depth": 0],
                ],
            ],
        ])

        guard let component, case let .list(items) = component.content else {
            return XCTFail("structured list must use the native list renderer")
        }
        XCTAssertEqual(items.map(\.marker), ["1.", "2."])
        XCTAssertEqual(items.map(\.text), ["保持样本外封存", "记录每个窗口"])
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

    #if os(macOS)
    func testInlineCodeHasVisiblePaddingAndRoundedBackgroundMetrics() {
        let rendered = ResearchInlineAttributedString.make(
            "公式使用 `SgCPSVol` 版本"
        )
        let value = rendered.string
        let paddedCode = [
            ResearchInlineAttributedString.horizontalPadding,
            "SgCPSVol",
            ResearchInlineAttributedString.horizontalPadding,
        ].joined()
        let range = (value as NSString).range(of: paddedCode)

        XCTAssertNotEqual(range.location, NSNotFound)
        XCTAssertEqual(
            rendered.attribute(
                ResearchInlineCodeLayoutManager.attribute,
                at: range.location,
                effectiveRange: nil
            ) as? Bool,
            true
        )
        XCTAssertGreaterThanOrEqual(
            ResearchInlineCodeLayoutManager.horizontalBackgroundOutset, 1
        )
        XCTAssertGreaterThanOrEqual(
            ResearchInlineCodeLayoutManager.verticalBackgroundOutset, 1
        )
        XCTAssertGreaterThanOrEqual(
            ResearchInlineCodeLayoutManager.cornerRadius, 5
        )
    }
    #endif

    func testTypedReferenceIsParsedFromRichTextAndKeepsItsDomainIcon() {
        let segments = ResearchDocumentTypedLinkParser.segments(in:
            "结果见 [回测统计](factortester://evidence/evidence%3Abacktest-1)"
        )

        XCTAssertEqual(segments.count, 2)
        guard case let .reference(reference) = segments[1] else {
            return XCTFail("typed reference must be parsed from rich text")
        }
        XCTAssertEqual(reference.kind, "evidence")
        XCTAssertEqual(reference.targetRef, "evidence:backtest-1")
        XCTAssertEqual(reference.label, "回测统计")
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.symbol(for: reference.kind),
            "doc.text.magnifyingglass"
        )
        XCTAssertEqual(reference.url?.scheme, "factortester")
        XCTAssertEqual(
            ResearchDocumentTypedLinkParser.reference(from: reference.url!)?.targetRef,
            "evidence:backtest-1"
        )
    }

    func testRelativeResearchFilesBecomeTypedLinksOutsideInlineCode() {
        let segments = ResearchDocumentTypedLinkParser.segments(in:
            "参见 grill/core-signal.md，但保留 `grill/raw-note.md`"
        )

        XCTAssertEqual(segments.count, 3)
        guard case let .reference(reference) = segments[1] else {
            return XCTFail("bare research file path must become a link")
        }
        XCTAssertEqual(reference.kind, "file")
        XCTAssertEqual(reference.targetRef, "grill/core-signal.md")
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.symbol(for: reference.kind),
            "doc.text"
        )
        guard case let .text(remainder) = segments[2] else {
            return XCTFail("inline code must remain ordinary rich text")
        }
        XCTAssertTrue(remainder.contains("`grill/raw-note.md`"))
    }

    func testMarkdownResearchFileLinkKeepsItsAuthoredLabel() {
        let segments = ResearchDocumentTypedLinkParser.segments(in:
            "参见 [核心信号审计](grill/2026-07-28-04-core-signal-over-modifiers.md)"
        )

        guard case let .reference(reference) = segments.last else {
            return XCTFail("relative Markdown file link must use the typed router")
        }
        XCTAssertEqual(reference.label, "核心信号审计")
        XCTAssertEqual(
            reference.targetRef,
            "grill/2026-07-28-04-core-signal-over-modifiers.md"
        )
    }

    func testWebLinksUseOneTypedIconRoute() {
        let segments = ResearchDocumentTypedLinkParser.segments(in:
            "参见 [事件文档](https://nautilustrader.io/docs/latest/concepts/events/)"
        )

        guard case let .reference(reference) = segments.last else {
            return XCTFail("web Markdown link must use the shared reference renderer")
        }
        XCTAssertEqual(reference.kind, "url")
        XCTAssertEqual(reference.label, "事件文档")
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.symbol(for: reference.kind),
            "safari"
        )
        XCTAssertEqual(
            ResearchDocumentReferenceRouter.webURL(for: reference)?.host,
            "nautilustrader.io"
        )
        XCTAssertNil(ResearchDocumentReferenceRouter.webURL(for: .init(
            kind: "url", targetRef: "file:///tmp/secret", label: "本地文件"
        )))
    }

    func testFactorAndProductReferencesUseDomainPresentation() {
        let factor = ResearchDocumentTypedLinkParser.segments(in:
            "[SgCPS](factortester://factor_family/factor-family%3ASgCPS)"
        )
        let product = ResearchDocumentTypedLinkParser.segments(in:
            "[工业硅](factortester://product/product%3ASI.GFE)"
        )

        guard case let .reference(factorRef) = factor.first,
              case let .reference(productRef) = product.first else {
            return XCTFail("domain objects must parse as typed references")
        }
        XCTAssertEqual(factorRef.kind, "factor_family")
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.tint(for: factorRef.kind),
            .factor
        )
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.symbol(for: factorRef.kind),
            "square.stack.3d.up"
        )
        XCTAssertEqual(productRef.kind, "product")
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.tint(for: productRef.kind),
            .product
        )
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.symbol(for: productRef.kind),
            "shippingbox"
        )
    }

    func testEvidenceReferenceKeepsSystemLinkTint() {
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.tint(for: "evidence"),
            .link
        )
        #if os(macOS)
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.nsColor(for: "evidence"),
            .controlAccentColor
        )
        #endif
    }

    func testLocalFileRouterStaysInsideResearchPackage() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let authoring = root.appendingPathComponent(
            "branches/main/authoring", isDirectory: true
        )
        let grill = root.appendingPathComponent("grill", isDirectory: true)
        try FileManager.default.createDirectory(
            at: authoring, withIntermediateDirectories: true
        )
        try FileManager.default.createDirectory(
            at: grill, withIntermediateDirectories: true
        )
        let file = grill.appendingPathComponent("note.md")
        try Data().write(to: file)
        defer { try? FileManager.default.removeItem(at: root) }
        let reportRef = authoring.appendingPathComponent("HEAD.json").absoluteString

        XCTAssertEqual(
            ResearchDocumentReferenceRouter.localFileURL(
                for: .init(kind: "file", targetRef: "grill/note.md", label: "说明"),
                reportRef: reportRef
            ),
            file
        )
        XCTAssertNil(ResearchDocumentReferenceRouter.localFileURL(
            for: .init(kind: "file", targetRef: "../note.md", label: "越界"),
            reportRef: reportRef
        ))
    }

    func testJobReferenceResolvesOnlySafeDurableJobIdentifiers() {
        let reference = ResearchDocumentTypedLink(
            kind: "job",
            targetRef: "research-job:job-2026_07.29",
            label: "回测任务"
        )

        XCTAssertEqual(
            ResearchDocumentReferenceRouter.jobID(from: reference),
            "job-2026_07.29"
        )
        XCTAssertNil(ResearchDocumentReferenceRouter.jobID(from: .init(
            kind: "job",
            targetRef: "research-job:../secret",
            label: "无效任务"
        )))
    }

    func testBindingKeepsBoundedStructuredDetailFields() {
        let binding = ResearchDocumentParser.parseBinding([
            "binding_id": "evidence-binding",
            "component_id": "finding",
            "kind": "evidence",
            "target_ref": "evidence:one",
            "label": "收益证据",
            "data": [
                "claim_summary": "手续费后收益为正",
                "scope": ["sample": "2025"],
            ],
        ])

        XCTAssertEqual(
            binding?.detailFields,
            [
                .init(name: "claim_summary", value: "手续费后收益为正"),
                .init(name: "scope.sample", value: "2025"),
            ]
        )
    }

    func testUnknownGraphNodeKeepsItsRegisteredName() {
        XCTAssertEqual(ResearchDisplayText.node("custom_review"), "custom review")
    }
}
