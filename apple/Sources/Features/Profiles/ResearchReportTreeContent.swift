import SwiftUI

extension ResearchReportTreePage {
    var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.largeTitle.weight(.bold))
            Text(L10n.format(
                "由 %@ 负责 · 当前阶段：%@",
                profileName,
                ResearchDisplayText.node(currentNode)
            ))
            .font(.callout)
            .foregroundStyle(.secondary)
            Text(L10n.text(
                "研究节点进入后自动建立章节，正文和证据可在本地报告中继续补充。"
            ))
            .font(.subheadline)
            .foregroundStyle(.secondary)
        }
    }

    var rootComponentIDs: [String] {
        chapterOrder.filter { rootComponentsByID[$0] != nil }
    }

    var scrollExecutionKey: ResearchReportScrollExecutionKey {
        let request = scrollRequest
        return ResearchReportScrollExecutionKey(
            token: request?.token ?? -1,
            targetIsLoaded: request.map {
                rootComponentsByID[$0.componentID] != nil
            } ?? false
        )
    }

    @ViewBuilder
    func chapterSlot(_ componentID: String) -> some View {
        if let component = rootComponentsByID[componentID] {
            ResearchDocumentComponentView(
                component: component,
                children: childrenByParent[component.id] ?? [],
                childrenByParent: childrenByParent,
                componentBindings: bindingsByComponent[component.id] ?? [],
                bindingsByComponent: bindingsByComponent,
                assets: assets,
                reportRef: reportRef
            )
            .accessibilityIdentifier(
                "research.report.chapter.\(componentID)"
            )
            .background {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(Color.primary.opacity(
                        highlightedComponentID == component.id ? 0.08 : 0
                    ))
                    .padding(-10)
            }
            .transition(.opacity)
        }
    }

    var materializedChapterOrder: [String] {
        chapterOrder.filter { rootComponentsByID[$0] != nil }
    }
}
