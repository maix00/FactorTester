import SwiftUI

struct ResearchDocumentRichTextView: View {
    let blocks: [ResearchDocumentTextBlock]

    init(text: String) {
        blocks = ResearchDocumentParser.textBlocks(text)
    }

    var body: some View {
        LazyVStack(alignment: .leading, spacing: ResearchDocumentTextMetrics.blockSpacing) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                switch block {
                case let .text(value):
                    ResearchDocumentInlineTextView(text: value)
                case let .list(items):
                    ResearchDocumentListView(items: items)
                case let .code(language, source):
                    ClientCodeBlock(source: source, language: language)
                case let .table(columns, rows):
                    ResearchDocumentTableView(columns: columns, rows: rows, source: nil)
                case let .math(latex):
                    RenderedMathFormulaView(latex: latex, fallback: "")
                }
            }
        }
    }
}

struct ResearchDocumentInlineTextView: View {
    let text: String
    @Environment(\.researchDocumentReferenceAction) private var openReference
    @Environment(\.researchDocumentReferenceComponentID) private var componentID
    @Environment(\.researchDocumentReferenceBindings) private var bindings

    var body: some View {
        if ResearchReportTextProjection.containsMath(text) {
            RenderedInlineMathTextView(text: text)
        } else {
            #if os(macOS)
            ResearchDocumentInlineTextMac(
                text: text,
                referenceScope: referenceScope,
                openReference: openLocatedReference
            )
            #else
            ResearchDocumentTypedLinkParser.renderedText(
                text,
                scope: referenceScope
            )
                .environment(\.openURL, OpenURLAction { url in
                    guard let reference = ResearchDocumentTypedLinkParser.reference(
                        from: url, preservingLabelIn: text
                    ), let trusted = referenceScope.trusted(reference) else {
                        return .systemAction
                    }
                    openReference(trusted)
                    return .handled
                })
                .textSelection(.enabled)
                .lineSpacing(ResearchDocumentTextMetrics.lineSpacing)
            #endif
        }
    }

    private func openLocatedReference(_ reference: ResearchDocumentTypedLink) {
        guard let trusted = referenceScope.trusted(reference) else { return }
        openReference(trusted)
    }

    private var referenceScope: ResearchDocumentReferenceScope {
        .init(componentID: componentID, bindings: bindings)
    }
}

enum ResearchDocumentTextMetrics {
    /// Mirrors the relaxed reading rhythm used for report prose and lists.
    static let lineSpacing: CGFloat = 5
    static let blockSpacing: CGFloat = 12
    static let listItemSpacing: CGFloat = 7
    static let nestedListIndent: CGFloat = 24
}

enum ResearchDocumentInlineTextStyle {
    static func markdown(_ text: String) -> AttributedString {
        var value = (try? AttributedString(markdown: text, options: .init(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        ))) ?? AttributedString(text)
        for run in value.runs {
            guard run.inlinePresentationIntent?.contains(.code) == true else {
                continue
            }
            value[run.range].font = .system(.body, design: .monospaced)
            value[run.range].backgroundColor = Color.secondary.opacity(0.14)
        }
        return value
    }
}

struct ResearchDocumentListView: View {
    let items: [ResearchDocumentListItem]
    @State private var showsAllItems = false

    var body: some View {
        LazyVStack(alignment: .leading, spacing: ResearchDocumentTextMetrics.listItemSpacing) {
            ForEach(visibleItems) { item in
                ResearchDocumentInlineTextView(text: item.text)
                    .padding(
                        .leading,
                        ResearchDocumentListPresentation.textIndent(
                            depth: item.depth
                        )
                    )
                    .overlay(alignment: .topLeading) {
                    Text(item.marker)
                        .font(.body.weight(.medium))
                        .frame(
                            width: ResearchDocumentListPresentation.markerWidth,
                            alignment: .trailing
                        )
                        .padding(
                            .leading,
                            CGFloat(item.depth)
                                * ResearchDocumentTextMetrics.nestedListIndent
                        )
                        .padding(.top, 1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if items.count > ResearchDocumentListPresentation.previewCount {
                Button {
                    withAnimation(.easeInOut(duration: 0.16)) {
                        showsAllItems.toggle()
                    }
                } label: {
                    Label(
                        showsAllItems
                            ? L10n.text("收起")
                            : L10n.format(
                                "显示其余 %d 项",
                                items.count
                                    - ResearchDocumentListPresentation.previewCount
                            ),
                        systemImage: showsAllItems
                            ? "chevron.up" : "chevron.down"
                    )
                    .font(.callout)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
                .padding(.leading, ResearchDocumentListPresentation.markerWidth + 7)
                .accessibilityIdentifier("research.report.list.toggle")
            }
        }
    }

    private var visibleItems: ArraySlice<ResearchDocumentListItem> {
        items.prefix(
            ResearchDocumentListPresentation.visibleCount(
                itemCount: items.count,
                showsAllItems: showsAllItems
            )
        )
    }
}

enum ResearchDocumentListPresentation {
    static let previewCount = 3
    static let markerWidth: CGFloat = 22

    static func visibleCount(
        itemCount: Int,
        showsAllItems: Bool
    ) -> Int {
        showsAllItems ? itemCount : min(itemCount, previewCount)
    }

    static func textIndent(depth: Int) -> CGFloat {
        CGFloat(depth) * ResearchDocumentTextMetrics.nestedListIndent
            + markerWidth + 7
    }

    static func hidesInternalHeading(
        kind: String,
        title: String,
        body: String
    ) -> Bool {
        if kind == "list" {
            return true
        }
        let genericTitles = Set(["列表", L10n.text("列表")])
        guard kind == "entry",
              genericTitles.contains(title.trimmingCharacters(
                in: .whitespacesAndNewlines
              )) else {
            return false
        }
        let blocks = ResearchDocumentParser.textBlocks(body)
        guard blocks.count == 1,
              case .list = blocks[0] else {
            return false
        }
        return true
    }
}
