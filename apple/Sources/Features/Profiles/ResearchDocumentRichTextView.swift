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

    var body: some View {
        if ResearchReportTextProjection.containsMath(text) {
            RenderedInlineMathTextView(text: text)
        } else {
            #if os(macOS)
            ResearchDocumentInlineTextMac(
                text: text, openReference: openReference
            )
            #else
            ResearchDocumentTypedLinkParser.renderedText(text)
                .environment(\.openURL, OpenURLAction { url in
                    guard let parsed = ResearchDocumentTypedLinkParser.reference(
                        from: url
                    ) else { return .systemAction }
                    let original = ResearchDocumentTypedLinkParser.segments(in: text)
                        .compactMap { segment -> ResearchDocumentTypedLink? in
                            guard case let .reference(reference) = segment,
                                  reference.kind == parsed.kind,
                                  reference.targetRef == parsed.targetRef else {
                                return nil
                            }
                            return reference
                        }.first ?? parsed
                    openReference(original)
                    return .handled
                })
                .textSelection(.enabled)
                .lineSpacing(ResearchDocumentTextMetrics.lineSpacing)
            #endif
        }
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

    var body: some View {
        LazyVStack(alignment: .leading, spacing: ResearchDocumentTextMetrics.listItemSpacing) {
            ForEach(items) { item in
                HStack(alignment: .firstTextBaseline, spacing: 7) {
                    Text(item.marker)
                        .font(.body.weight(.medium))
                        .frame(minWidth: 22, alignment: .trailing)
                    ResearchDocumentInlineTextView(text: item.text)
                }
                .padding(.leading, CGFloat(item.depth)
                    * ResearchDocumentTextMetrics.nestedListIndent)
            }
        }
    }
}
