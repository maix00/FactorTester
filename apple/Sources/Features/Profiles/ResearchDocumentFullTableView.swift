import SwiftUI

struct ResearchDocumentFullTableView: View {
    let source: ResearchDocumentTableSource

    @Environment(\.dismiss) private var dismiss
    @State private var page = 0
    @State private var loaded: ResearchDocumentJobTablePage?
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text(L10n.text("完整统计表")).font(.title3.weight(.semibold))
                    Text(source.filename).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button(L10n.text("完成")) { dismiss() }
            }
            content
            HStack {
                Button(L10n.text("上一页")) { page -= 1 }.disabled(page == 0)
                Text(L10n.format("第 %lld 页", Int64(page + 1)))
                    .font(.caption).foregroundStyle(.secondary)
                Button(L10n.text("下一页")) { page += 1 }
                    .disabled(loaded?.hasMore != true)
                Spacer()
                Text(L10n.format(
                    "每页 %lld 行", Int64(ResearchDocumentJobTableReader.pageSize)
                ))
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(20)
        .frame(minWidth: 760, minHeight: 520)
        .task(id: page) { await load() }
    }

    @ViewBuilder
    private var content: some View {
        if let loaded {
            ResearchDocumentTableView(
                columns: loaded.columns, rows: loaded.rows, source: nil,
                maximumHeight: 560
            )
        } else if let error {
            VStack(spacing: 8) {
                Label(L10n.text("无法读取完整统计表"),
                      systemImage: "tablecells.badge.ellipsis")
                    .font(.headline)
                Text(error).font(.callout).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            ProgressView(L10n.text("正在按页读取统计表…"))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func load() async {
        loaded = nil
        error = nil
        do {
            loaded = try await ResearchDocumentJobTableReader.load(
                source: source, page: page
            )
        } catch {
            self.error = error.localizedDescription
        }
    }
}
