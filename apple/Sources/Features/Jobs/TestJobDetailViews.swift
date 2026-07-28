import SwiftUI
import Charts

struct TestJobFieldTable: View {
    let title: String
    let rows: [TestJobField]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L10n.resource(title)).font(.headline)
            if rows.isEmpty {
                Text("暂无字段").font(.caption).foregroundStyle(.secondary)
            } else {
                Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 6) {
                    GridRow {
                        Text("字段").font(.caption.bold()).foregroundStyle(.secondary)
                        Text("值").font(.caption.bold()).foregroundStyle(.secondary)
                    }
                    Divider().gridCellUnsizedAxes(.horizontal)
                    ForEach(rows) { row in
                        GridRow {
                            fieldName(row).font(.caption)
                                .frame(minWidth: 150, alignment: .leading)
                            Text(row.value)
                                .font(.caption)
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(.quaternary.opacity(0.24), in: RoundedRectangle(cornerRadius: 7))
            }
        }
    }

    private func fieldName(_ row: TestJobField) -> Text {
        if let nameKey = row.nameKey {
            if let nameArgument = row.nameArgument {
                return Text(verbatim: L10n.format(nameKey, nameArgument))
            }
            return Text(L10n.resource(nameKey))
        }
        return Text(verbatim: row.name)
    }
}

struct TestJobArtifactGrid: View {
    let artifacts: [TestJobArtifact]
    let onOpen: (TestJobArtifact) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 6) {
                GridRow {
                    Text("中文描述").font(.caption.bold()).foregroundStyle(.secondary)
                    Text("原文件名").font(.caption.bold()).foregroundStyle(.secondary)
                    Text("文件大小").font(.caption.bold()).foregroundStyle(.secondary)
                }
                Divider().gridCellUnsizedAxes(.horizontal)
                ForEach(artifacts) { artifact in
                    GridRow {
                        Text(artifact.description).font(.caption)
                        Button(artifact.fileName) { onOpen(artifact) }
                            .buttonStyle(.link)
                            .font(.caption)
                            .lineLimit(1)
                        Text(ByteCountFormatter.string(fromByteCount: Int64(artifact.sizeBytes), countStyle: .file))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(10)
            .background(.quaternary.opacity(0.24), in: RoundedRectangle(cornerRadius: 7))
        }
    }
}

struct TestJobResultSectionView: View {
    let section: TestJobResultSection
    let isExpanded: Bool
    let onExpansionChanged: (Bool) -> Void

    var body: some View {
        DisclosureGroup(
            isExpanded: Binding(get: { isExpanded }, set: onExpansionChanged),
            content: { content },
            label: { Text(L10n.resource(section.title)).font(.headline) }
        )
    }

    @ViewBuilder private var content: some View {
        switch section.kind {
        case .chart:
            Chart(section.chartPoints) { point in
                LineMark(
                    x: .value(L10n.text("时点"), point.id),
                    y: .value(L10n.text("数值"), point.value)
                )
                PointMark(
                    x: .value(L10n.text("时点"), point.id),
                    y: .value(L10n.text("数值"), point.value)
                )
            }
            .chartXAxis { AxisMarks(values: .automatic) }
            .chartYAxis { AxisMarks(position: .leading) }
            .frame(height: 210)
        case .table:
            if let first = section.rows.first {
                let columns = first.keys.sorted().prefix(24)
                ScrollView(.horizontal) {
                    Grid(horizontalSpacing: 12, verticalSpacing: 6) {
                        GridRow { ForEach(columns, id: \.self) { Text($0).font(.caption.bold()) } }
                        ForEach(section.rows.prefix(30).indices, id: \.self) { index in
                            GridRow { ForEach(columns, id: \.self) { Text(section.rows[index][$0] ?? "").font(.caption) } }
                        }
                    }
                    .padding(8)
                    .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 6))
                }
            }
        case .json:
            ClientCodeBlock(
                source: section.jsonText, language: "json", maximumHeight: 180
            )
        }
    }
}
