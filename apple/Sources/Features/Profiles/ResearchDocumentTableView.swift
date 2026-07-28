import SwiftUI

struct ResearchDocumentTableView: View {
    let columns: [String]
    let rows: [[String]]

    var body: some View {
        ScrollView([.horizontal, .vertical], showsIndicators: true) {
            VStack(alignment: .leading, spacing: 0) {
                row(columns, header: true)
                ForEach(Array(rows.enumerated()), id: \.offset) { index, values in
                    row(values, header: false)
                        .background(index.isMultiple(of: 2)
                            ? Color.clear : Color.secondary.opacity(0.035))
                }
            }
            .overlay {
                RoundedRectangle(cornerRadius: 7)
                    .stroke(Color.secondary.opacity(0.18), lineWidth: 1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: 420, alignment: .leading)
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
}

private struct ResearchDocumentTableCell: View {
    let text: String
    let header: Bool

    var body: some View {
        Group {
            if ResearchReportTextProjection.containsMath(text) {
                RenderedInlineMathTextView(text: text)
            } else {
                Text(text)
                    .textSelection(.enabled)
            }
        }
        .font(header ? .caption.weight(.semibold) : .callout)
        .frame(minHeight: 24, alignment: .topLeading)
    }
}
