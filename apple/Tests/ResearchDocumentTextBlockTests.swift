import XCTest
@testable import FTClient

final class ResearchDocumentTextBlockTests: XCTestCase {
    func testTypedLinkLabelUnescapesFactorParameterBrackets() {
        let target = "factor%3Av2%3A" + String(repeating: "a", count: 43)
        let segments = ResearchDocumentTypedLinkParser.segments(
            in: "[SgCPS|P:\\[CA\\]|N:20d](factortester://factor/\(target))"
        )

        guard case let .reference(reference) = segments.first else {
            return XCTFail("escaped bracket label must remain a typed link")
        }
        XCTAssertEqual(reference.label, "SgCPS|P:[CA]|N:20d")
    }

    func testTypedLinkLabelKeepsNestedFactorParameterBrackets() {
        let target = "factor%3Av2%3A" + String(repeating: "a", count: 43)
        let segments = ResearchDocumentTypedLinkParser.segments(
            in: "[SgCPS|P:[[CA]]|N:[[20d]]](factortester://factor/\(target))"
        )

        guard case let .reference(reference) = segments.first else {
            return XCTFail("nested bracket label must remain a typed link")
        }
        XCTAssertEqual(reference.label, "SgCPS|P:[[CA]]|N:[[20d]]")
    }

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

    func testInlineMathTokensPreserveSurroundingSpacing() {
        XCTAssertEqual(
            ResearchInlineMathTokens.parse("MmTrend = \\(P_t\\)，继续"),
            [
                .text("MmTrend = "),
                .formula("P_t"),
                .text("，继续"),
            ]
        )
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

    func testLongListUsesThreeItemPreviewAndCanExpand() {
        XCTAssertEqual(
            ResearchDocumentListPresentation.visibleCount(
                itemCount: 5,
                showsAllItems: false
            ),
            3
        )
        XCTAssertEqual(
            ResearchDocumentListPresentation.visibleCount(
                itemCount: 5,
                showsAllItems: true
            ),
            5
        )
    }

    func testOnlyGeneratedListHeadingIsHidden() {
        XCTAssertTrue(
            ResearchDocumentListPresentation.hidesInternalHeading(
                kind: "entry",
                title: "列表",
                body: "- 第一项\n- 第二项"
            )
        )
        XCTAssertFalse(
            ResearchDocumentListPresentation.hidesInternalHeading(
                kind: "entry",
                title: "研究约束",
                body: "- 第一项\n- 第二项"
            )
        )
        XCTAssertFalse(
            ResearchDocumentListPresentation.hidesInternalHeading(
                kind: "entry",
                title: "列表",
                body: "说明\n\n- 第一项"
            )
        )
    }

    func testStructuralContentLabelsAreNeverRenderedAsHeadings() {
        for item in [
            ("entry", "正文", "结论"),
            ("table", "表格", ""),
            ("list", "列表", "")
        ] {
            XCTAssertTrue(
                ResearchDocumentListPresentation.hidesInternalHeading(
                    kind: item.0,
                    title: item.1,
                    body: item.2
                )
            )
        }
        XCTAssertFalse(
            ResearchDocumentListPresentation.hidesInternalHeading(
                kind: "table",
                title: "参数比较",
                body: ""
            )
        )
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
    func testInlineCodeAllocatesCompactInnerAndOuterHorizontalSpacing() {
        let rendered = ResearchInlineAttributedString.make(
            "若`SgCPSVol`成立"
        )
        let value = rendered.string
        let range = (value as NSString).range(of: "SgCPSVol")

        XCTAssertNotEqual(range.location, NSNotFound)
        XCTAssertEqual(
            value,
            "若\u{200a}\u{00a0}SgCPSVol\u{00a0}\u{200a}成立"
        )
        XCTAssertEqual(
            rendered.attribute(
                ResearchInlineCodeLayoutManager.attribute,
                at: range.location,
                effectiveRange: nil
            ) as? Bool,
            true
        )
        XCTAssertEqual(
            ResearchInlineCodeLayoutManager.horizontalBackgroundOutset, 0
        )
        XCTAssertEqual(
            ResearchInlineCodeLayoutManager.verticalBackgroundOutset, 0.5
        )
        XCTAssertEqual(ResearchInlineCodeLayoutManager.cornerRadius, 6)
    }

    func testInlineCodeKeepsExistingOuterWhitespace() {
        let rendered = ResearchInlineAttributedString.make(
            "公式使用 `SgCPSVol` 版本"
        )

        XCTAssertEqual(
            rendered.string,
            "公式使用 \u{00a0}SgCPSVol\u{00a0} 版本"
        )
    }

    func testWrappedInlineCodeDrawsOnlyCompactVisibleFragments() {
        let storage = NSTextStorage(
            attributedString: ResearchInlineAttributedString.make(
                "前缀 `CrossSectionalOpAndAnotherLongIdentifier` 后缀"
            )
        )
        let layout = ResearchInlineCodeLayoutManager()
        let container = NSTextContainer(
            containerSize: NSSize(width: 120, height: 1_000)
        )
        container.lineFragmentPadding = 0
        layout.addTextContainer(container)
        storage.addLayoutManager(layout)
        layout.ensureLayout(for: container)

        let full = NSRange(location: 0, length: storage.length)
        var codeRange = NSRange(location: NSNotFound, length: 0)
        storage.enumerateAttribute(
            ResearchInlineCodeLayoutManager.attribute,
            in: full
        ) { value, range, stop in
            guard value != nil else { return }
            codeRange = range
            stop.pointee = true
        }
        let rects = layout.backgroundRects(
            forCharacterRange: codeRange,
            visibleGlyphRange: layout.glyphRange(for: container),
            in: container
        )
        let font = storage.attribute(
            .font,
            at: codeRange.location,
            effectiveRange: nil
        ) as! NSFont

        XCTAssertGreaterThan(rects.count, 1)
        XCTAssertTrue(rects.allSatisfy { $0.width > 1 })
        XCTAssertTrue(rects.allSatisfy {
            $0.height <= ceil(font.ascender - font.descender) + 1
        })
    }

    func testInlineCodeBackgroundKeepsSameDescentAcrossWrappedLines() {
        let storage = NSTextStorage(
            attributedString: ResearchInlineAttributedString.make(
                "`FIRST` 后面是一段足以触发行宽换行的正文，"
                    + "继续补充一些文字直到 `LAST` 位于后续行"
            )
        )
        let layout = ResearchInlineCodeLayoutManager()
        let container = NSTextContainer(
            containerSize: NSSize(width: 190, height: 1_000)
        )
        container.lineFragmentPadding = 0
        layout.addTextContainer(container)
        storage.addLayoutManager(layout)
        layout.ensureLayout(for: container)

        var codeRanges: [NSRange] = []
        storage.enumerateAttribute(
            ResearchInlineCodeLayoutManager.attribute,
            in: NSRange(location: 0, length: storage.length)
        ) { value, range, _ in
            if value != nil { codeRanges.append(range) }
        }
        XCTAssertEqual(codeRanges.count, 2)

        let visible = layout.glyphRange(for: container)
        let measurements = codeRanges.compactMap { range -> (CGFloat, CGFloat)? in
            let glyphs = layout.glyphRange(
                forCharacterRange: range,
                actualCharacterRange: nil
            )
            guard let background = layout.backgroundRects(
                forCharacterRange: range,
                visibleGlyphRange: visible,
                in: container
            ).first else { return nil }
            let line = layout.lineFragmentRect(
                forGlyphAt: glyphs.location,
                effectiveRange: nil
            )
            let baseline = line.minY
                + layout.location(forGlyphAt: glyphs.location).y
            return (line.minY, background.maxY - baseline)
        }

        XCTAssertEqual(measurements.count, 2)
        XCTAssertNotEqual(measurements[0].0, measurements[1].0)
        XCTAssertEqual(measurements[0].1, measurements[1].1, accuracy: 0.01)
        let font = storage.attribute(
            .font,
            at: codeRanges[1].location,
            effectiveRange: nil
        ) as! NSFont
        let compactDescent = -font.descender
            + ResearchInlineCodeLayoutManager.verticalBackgroundOutset
        XCTAssertEqual(measurements[0].1, compactDescent, accuracy: 0.01)
        XCTAssertEqual(measurements[1].1, compactDescent, accuracy: 0.01)
    }
    #endif

    func testTableColumnsGiveCodeEnoughWidthWithoutFlatteningAllColumns() {
        let widths = ResearchDocumentTableLayout.columnWidths(
            columns: ["状态", "约束变化"],
            rows: [[
                "待处理 (open)",
                "`hypothesis_validity.mechanism_chain`, "
                    + "`hypothesis_validity.alternative_explanations`",
            ]]
        )

        XCTAssertEqual(widths.count, 2)
        XCTAssertGreaterThan(widths[1], widths[0])
        XCTAssertLessThanOrEqual(
            widths[0],
            ResearchDocumentTableLayout.maximumTextColumnWidth
        )
        XCTAssertLessThanOrEqual(
            widths[1],
            ResearchDocumentTableLayout.maximumCodeColumnWidth
        )
    }

    func testTableOnlyClipsContentThatClearlyExceedsMaximumHeight() {
        XCTAssertEqual(
            ResearchDocumentTableLayout.visibleHeight(500, maximum: 420),
            500
        )
        XCTAssertEqual(
            ResearchDocumentTableLayout.visibleHeight(541, maximum: 420),
            420
        )
    }

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

    func testResearchRootFileBecomesTypedLocalLink() {
        let segments = ResearchDocumentTypedLinkParser.segments(
            in: "参见 [上下文](CONTEXT.md)"
        )

        XCTAssertEqual(
            segments,
            [
                .text("参见 "),
                .reference(.init(
                    kind: "file",
                    targetRef: "CONTEXT.md",
                    label: "上下文"
                )),
            ]
        )
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

    func testDomainReferencesUseSemanticPresentation() {
        let target = "factor-family%3Av2%3A" + String(
            repeating: "a", count: 43
        )
        let factor = ResearchDocumentTypedLinkParser.segments(in:
            "[SgCPS](factortester://factor/\(target))"
        )
        let product = ResearchDocumentTypedLinkParser.segments(in:
            "[工业硅](factortester://product/product%3ASI.GFE)"
        )

        guard case let .reference(factorRef) = factor.first,
              case let .reference(productRef) = product.first else {
            return XCTFail("domain objects must parse as typed references")
        }
        XCTAssertEqual(factorRef.kind, "factor")
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.tint(for: factorRef.kind),
            .factor
        )
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.symbol(for: factorRef.kind),
            "function"
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
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.tint(for: "profile"),
            .profile
        )
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.symbol(for: "profile"),
            "person.crop.rectangle.stack"
        )
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.tint(for: "contract"),
            .product
        )
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.symbol(
                for: "continuous_contract"
            ),
            "chart.line.uptrend.xyaxis"
        )
    }

    func testEvidenceReferenceKeepsFixedSystemBlueTint() {
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.tint(for: "evidence"),
            .evidence
        )
        #if os(macOS)
        XCTAssertEqual(
            ResearchDocumentTypedLinkPresentation.nsColor(for: "evidence"),
            .systemBlue
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
        let context = root.appendingPathComponent("CONTEXT.md")
        try Data().write(to: file)
        try Data().write(to: context)
        defer { try? FileManager.default.removeItem(at: root) }
        let reportRef = authoring.appendingPathComponent("HEAD.json").absoluteString

        XCTAssertEqual(
            ResearchDocumentReferenceRouter.localFileURL(
                for: .init(kind: "file", targetRef: "grill/note.md", label: "说明"),
                reportRef: reportRef
            ),
            file
        )
        XCTAssertEqual(
            ResearchDocumentReferenceRouter.localFileURL(
                for: .init(
                    kind: "file",
                    targetRef: "CONTEXT.md",
                    label: "上下文"
                ),
                reportRef: reportRef
            ),
            context
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

}
