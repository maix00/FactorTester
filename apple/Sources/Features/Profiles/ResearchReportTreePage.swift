import SwiftUI

struct ResearchReportTreePage: View {
    let title: String
    let profileName: String
    let currentNode: String
    let error: String?
    let components: [ResearchDocumentComponent]
    let assets: [ResearchDocumentAsset]
    let bindings: [ResearchDocumentBinding]
    let reportRef: String

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 18) {
                header
                if let error {
                    Label(error, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.secondary)
                } else if components.isEmpty {
                    ProgressView(L10n.text("正在读取本地研究报告…"))
                } else {
                    ForEach(rootComponents) { component in
                        ResearchDocumentComponentView(
                            component: component,
                            children: childrenByParent[component.id] ?? [],
                            childrenByParent: childrenByParent,
                            assets: assets,
                            bindings: bindings,
                            reportRef: reportRef
                        )
                        .id(component.id)
                        .transition(.opacity.combined(with: .move(edge: .bottom)))
                    }
                }
            }
            .frame(maxWidth: 820, alignment: .leading)
            .padding(.horizontal, 42)
            .padding(.vertical, 34)
            .frame(maxWidth: .infinity, alignment: .center)
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.largeTitle.weight(.bold))
            Text(L10n.format("由 %@ 负责 · 当前阶段：%@", profileName,
                             ResearchDisplayText.node(currentNode)))
                .font(.callout).foregroundStyle(.secondary)
            Text(L10n.text("研究节点进入后自动建立章节，正文和证据可在本地报告中继续补充。"))
                .font(.subheadline).foregroundStyle(.secondary)
        }
    }

    private var rootComponents: [ResearchDocumentComponent] {
        let roots = components.filter { $0.parentID == nil }
        let chapters = roots.filter { $0.kind == "chapter" }
        return chapters.isEmpty ? roots : chapters
    }

    private var childrenByParent: [String: [ResearchDocumentComponent]] {
        Dictionary(grouping: components.compactMap { component in
            component.parentID.map { ($0, component) }
        }, by: \.0).mapValues { $0.map(\.1) }
    }
}
