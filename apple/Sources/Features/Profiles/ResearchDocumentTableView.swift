import SwiftUI

struct ResearchDocumentTableView: View {
    let columns: [String]
    let rows: [[String]]
    let source: ResearchDocumentTableSource?
    var maximumHeight: CGFloat = 420

    @State private var showingFullTable = false

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            toolbar
            table
        }
        .sheet(isPresented: $showingFullTable) {
            if let source { ResearchDocumentFullTableView(source: source) }
        }
    }

    @ViewBuilder
    private var table: some View {
        if usesBatchedMathRenderer {
            ResearchDocumentMathTableView(
                columns: columns,
                rows: rows,
                maximumHeight: maximumHeight
            )
        } else {
            ScrollView([.horizontal, .vertical], showsIndicators: true) {
                LazyVStack(alignment: .leading, spacing: 0, pinnedViews: [.sectionHeaders]) {
                    Section {
                        ForEach(Array(rows.enumerated()), id: \.offset) { index, values in
                            row(values, header: false)
                                .background(index.isMultiple(of: 2)
                                    ? Color.clear : Color.secondary.opacity(0.035))
                        }
                    } header: {
                        row(columns, header: true)
                            .background(.background)
                    }
                }
                .overlay {
                    RoundedRectangle(cornerRadius: 7)
                        .stroke(Color.secondary.opacity(0.18), lineWidth: 1)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: maximumHeight, alignment: .leading)
        }
    }

    @ViewBuilder
    private var toolbar: some View {
        if let source {
            HStack(spacing: 9) {
                if source.isTruncated {
                    Text(L10n.format(
                        "报告中仅显示前 %lld 行、%lld 列",
                        Int64(rows.count), Int64(columns.count)
                    ))
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button(L10n.text("打开完整表格")) { showingFullTable = true }
                    .controlSize(.small)
            }
        }
    }

    @ViewBuilder
    private func row(_ values: [String], header: Bool) -> some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(values.enumerated()), id: \.offset) { _, value in
                ResearchDocumentTableCell(text: value, header: header)
                    .frame(width: 156, alignment: .leading)
                    .padding(8)
            }
        }
    }

    private var usesBatchedMathRenderer: Bool {
        (columns + rows.flatMap { $0 }).lazy
            .filter(ResearchReportTextProjection.containsMath)
            .prefix(6)
            .count == 6
    }
}

private struct ResearchDocumentTableCell: View {
    let text: String
    let header: Bool

    var body: some View {
        Group {
            if ResearchReportTextProjection.containsMath(text) {
                RenderedInlineMathTextView(text: text)
            } else {
                Text(text).textSelection(.enabled)
            }
        }
        .font(font)
        .frame(minHeight: 24, alignment: .topLeading)
    }

    private var font: Font {
        header ? .caption.weight(.semibold) : .callout
    }
}
