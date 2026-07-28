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
                    ResearchDocumentCodeView(language: language, source: source)
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
        (try? AttributedString(markdown: text, options: .init(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        ))) ?? AttributedString(text)
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

struct ResearchDocumentCodeView: View {
    let language: String
    let source: String

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(language).font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
            ScrollView([.horizontal, .vertical]) {
                Text(source)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
            }
            .frame(maxHeight: 260)
            .background(Color.black.opacity(0.045), in: RoundedRectangle(cornerRadius: 7))
        }
    }
}
