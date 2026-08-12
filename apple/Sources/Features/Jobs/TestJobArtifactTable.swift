import Foundation
import SwiftUI

struct TestJobArtifactColumnPresentation: Hashable {
    let presentation: String
    let kind: String
    let targetRefField: String
}

struct TestJobArtifactTable {
    let rows: [[String: String]]
    let columnPresentations: [String: TestJobArtifactColumnPresentation]

    var visibleColumns: [String] {
        let hidden = Set(columnPresentations.values.map(\.targetRefField))
        return Set(rows.flatMap(\.keys)).subtracting(hidden).sorted()
    }

    func presentation(
        for column: String
    ) -> TestJobArtifactColumnPresentation? {
        columnPresentations[column]
    }

    func referenceTarget(
        column: String,
        row: [String: String]
    ) -> String? {
        guard let field = presentation(for: column)?.targetRefField,
              let value = row[field], !value.isEmpty else { return nil }
        return value
    }
}

extension TestJobsService {
    static func decodeArtifactTable(_ data: Data) throws -> TestJobArtifactTable {
        guard let payload = try JSONSerialization.jsonObject(with: data)
                as? [String: Any],
              let rawRows = payload["rows"] as? [[String: Any]] else {
            throw TestJobsRequestError(
                statusCode: nil,
                responseText: L10n.text("生成物不是可识别的表格数据")
            )
        }
        let rows = rawRows.map { row in
            row.mapValues(Self.artifactCellValue)
        }
        let rawPresentations = payload["column_presentations"]
            as? [String: [String: Any]] ?? [:]
        let presentations: [String: TestJobArtifactColumnPresentation] =
            rawPresentations.compactMapValues { value in
                guard value["presentation"] as? String == "reference",
                      let kind = value["kind"] as? String,
                      let target = value["target_ref_field"] as? String,
                      !kind.isEmpty, !target.isEmpty else { return nil }
                return TestJobArtifactColumnPresentation(
                    presentation: "reference", kind: kind,
                    targetRefField: target
                )
            }
        return TestJobArtifactTable(
            rows: rows, columnPresentations: presentations
        )
    }

    private static func artifactCellValue(_ value: Any) -> String {
        if value is NSNull { return "" }
        if let value = value as? String { return value }
        if let value = value as? NSNumber { return value.stringValue }
        guard JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(
                withJSONObject: value, options: [.sortedKeys]
              ) else { return String(describing: value) }
        return String(data: data, encoding: .utf8) ?? ""
    }
}

struct TestJobArtifactTableView: View {
    let table: TestJobArtifactTable
    let openReference: (ResearchDocumentTypedLink) -> Void

    var body: some View {
        ScrollView(.horizontal) {
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 7) {
                GridRow {
                    ForEach(table.visibleColumns, id: \.self) { column in
                        Text(column).font(.caption.bold())
                    }
                }
                Divider().gridCellUnsizedAxes(.horizontal)
                ForEach(table.rows.indices, id: \.self) { index in
                    GridRow {
                        ForEach(table.visibleColumns, id: \.self) { column in
                            cell(column: column, row: table.rows[index])
                        }
                    }
                }
            }
            .padding(10)
        }
        .background(.quaternary.opacity(0.24), in: RoundedRectangle(cornerRadius: 7))
    }

    @ViewBuilder
    private func cell(column: String, row: [String: String]) -> some View {
        let label = row[column] ?? ""
        if let presentation = table.presentation(for: column),
           let target = table.referenceTarget(column: column, row: row) {
            Button {
                openReference(.init(
                    kind: presentation.kind,
                    targetRef: target,
                    label: label
                ))
            } label: {
                Label(
                    label,
                    systemImage: ResearchDocumentTypedLinkPresentation.symbol(
                        for: presentation.kind
                    )
                )
                .foregroundStyle(
                    ResearchDocumentTypedLinkPresentation.color(
                        for: presentation.kind
                    )
                )
            }
            .buttonStyle(.plain)
        } else {
            Text(label).font(.caption).textSelection(.enabled)
        }
    }
}
