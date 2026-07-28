import SwiftUI

struct ResearchDocumentRichTextView: View {
    let blocks: [ResearchDocumentTextBlock]

    init(text: String) {
        blocks = ResearchDocumentParser.textBlocks(text)
    }

    var body: some View {
        LazyVStack(alignment: .leading, spacing: 8) {
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

    var body: some View {
        if ResearchReportTextProjection.containsMath(text) {
            RenderedInlineMathTextView(text: text)
        } else {
            Text(markdown).textSelection(.enabled)
        }
    }

    private var markdown: AttributedString {
        ResearchDocumentInlineTextStyle.markdown(text)
    }
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
        LazyVStack(alignment: .leading, spacing: 5) {
            ForEach(items) { item in
                HStack(alignment: .firstTextBaseline, spacing: 7) {
                    Text(item.marker)
                        .font(.body.weight(.medium))
                        .frame(width: 26, alignment: .trailing)
                    ResearchDocumentInlineTextView(text: item.text)
                }
                .padding(.leading, CGFloat(item.depth) * 20)
            }
        }
    }
}
