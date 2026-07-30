import SwiftUI

struct ResearchDocumentTableView: View {
    let columns: [String]
    let rows: [[String]]
    let source: ResearchDocumentTableSource?
    var maximumHeight: CGFloat = 420

    @State private var showingFullTable = false
    @State private var measuredContentHeight: CGFloat = 0

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
            let widths = ResearchDocumentTableLayout.columnWidths(
                columns: columns,
                rows: rows
            )
            ScrollView([.horizontal, .vertical], showsIndicators: true) {
                LazyVStack(alignment: .leading, spacing: 0, pinnedViews: [.sectionHeaders]) {
                    Section {
                        ForEach(Array(rows.enumerated()), id: \.offset) { index, values in
                            row(values, header: false, widths: widths)
                                .background(index.isMultiple(of: 2)
                                    ? Color.clear : Color.secondary.opacity(0.035))
                        }
                    } header: {
                        row(columns, header: true, widths: widths)
                            .background(.background)
                    }
                }
                .background {
                    GeometryReader { proxy in
                        Color.clear.preference(
                            key: ResearchDocumentTableHeightKey.self,
                            value: proxy.size.height
                        )
                    }
                }
                .overlay {
                    RoundedRectangle(cornerRadius: 7)
                        .stroke(Color.secondary.opacity(0.18), lineWidth: 1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(
                height: ResearchDocumentTableLayout.visibleHeight(
                    measuredContentHeight,
                    maximum: maximumHeight
                )
            )
            .onPreferenceChange(ResearchDocumentTableHeightKey.self) {
                measuredContentHeight = $0
            }
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
    private func row(
        _ values: [String],
        header: Bool,
        widths: [CGFloat]
    ) -> some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(values.enumerated()), id: \.offset) { index, value in
                ResearchDocumentTableCell(text: value, header: header)
                    .frame(
                        width: index < widths.count
                            ? widths[index]
                            : ResearchDocumentTableLayout.minimumColumnWidth,
                        alignment: .leading
                    )
                    .padding(8)
            }
        }
    }

    private var usesBatchedMathRenderer: Bool {
        (columns + rows.flatMap { $0 })
            .contains(where: ResearchReportTextProjection.containsMath)
    }
}

enum ResearchDocumentTableLayout {
    static let minimumColumnWidth: CGFloat = 112
    static let maximumTextColumnWidth: CGFloat = 360
    static let maximumCodeColumnWidth: CGFloat = 520
    static let nearbyOverflowAllowance: CGFloat = 120

    static func columnWidths(
        columns: [String],
        rows: [[String]]
    ) -> [CGFloat] {
        columns.indices.map { index in
            let values = [columns[index]]
                + rows.compactMap { index < $0.count ? $0[index] : nil }
            let containsCode = values.contains {
                $0.range(of: #"`[^`\r\n]+`"#, options: .regularExpression)
                    != nil
            }
            let maximum = containsCode
                ? maximumCodeColumnWidth
                : maximumTextColumnWidth
            let contentWidth = values.map(estimatedWidth).max() ?? 0
            return min(maximum, max(minimumColumnWidth, contentWidth))
        }
    }

    static func visibleHeight(
        _ measured: CGFloat,
        maximum: CGFloat
    ) -> CGFloat {
        guard measured > 0 else { return maximum }
        return measured <= maximum + nearbyOverflowAllowance
            ? max(1, measured)
            : maximum
    }

    private static func estimatedWidth(_ source: String) -> CGFloat {
        let visible = source
            .replacingOccurrences(
                of: #"\[([^\]]+)\]\([^)]+\)"#,
                with: "$1",
                options: .regularExpression
            )
            .replacingOccurrences(of: "`", with: "")
        let units = visible.unicodeScalars.reduce(0.0) { result, scalar in
            result + (scalar.value > 0x7f ? 2 : 1)
        }
        return CGFloat(units * 7.2 + 24)
    }
}

private struct ResearchDocumentTableHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

private struct ResearchDocumentTableCell: View {
    let text: String
    let header: Bool

    var body: some View {
        Group {
            #if os(macOS)
            ResearchDocumentInlineTextView(text: text, nativeFont: nativeFont)
            #else
            ResearchDocumentInlineTextView(text: text)
            #endif
        }
        .font(font)
        .frame(minHeight: 24, alignment: .topLeading)
    }

    #if os(macOS)
    private var nativeFont: NSFont {
        if header {
            return .systemFont(
                ofSize: NSFont.smallSystemFontSize,
                weight: .semibold
            )
        }
        return .preferredFont(forTextStyle: .callout)
    }
    #endif

    private var font: Font {
        header ? .caption.weight(.semibold) : .callout
    }
}
