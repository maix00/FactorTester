import Foundation
import SwiftUI

private struct LocalReportComponent: Identifiable {
    let id: String
    let kind: String
    let parentID: String?
    let title: String
    let body: String
    let content: String
}

struct ResearchDocumentReportView: View {
    let detail: ProfileResearchDetail
    let workPackage: ProfileResearchWorkPackageDetail
    let steps: [ResearchTransitionStep]
    let nextCursor: String?
    let profileName: String
    let reportTitle: String
    let artifact: ResearchArtifactModel
    let selectBranch: (String) -> Void
    let loadEarlier: () async -> Void

    @State private var title = ""
    @State private var components: [LocalReportComponent] = []
    @State private var error: String?
    @State private var selectedCheckpointRef = ""

    var body: some View {
        HStack(spacing: 0) {
            ResearchVersionTreePane(
                detail: detail,
                workPackage: workPackage,
                steps: steps,
                sectionRefsByCheckpoint: navigationSectionRefs,
                sectionRefsByNode: navigationSectionRefs,
                selectedCheckpointRef: $selectedCheckpointRef,
                select: selectCheckpoint,
                loadEarlier: loadEarlier,
                canLoadEarlier: nextCursor != nil
            )
            .frame(width: ResearchTreeLayout.navigatorWidth)
            .clipped()
            Divider()
            report
        }
        .task(id: artifact.localRef) {
            await load()
        }
    }

    private var report: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    header
                    if let error {
                        Label(error, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.secondary)
                    } else if components.isEmpty {
                        ProgressView(L10n.text("正在读取本地研究报告…"))
                    } else {
                        ForEach(components.filter { $0.kind == "chapter" }) {
                            chapter in
                            chapterView(chapter)
                        }
                    }
                }
                .frame(maxWidth: 820, alignment: .leading)
                .padding(.horizontal, 42)
                .padding(.vertical, 34)
                .frame(maxWidth: .infinity, alignment: .center)
            }
            .onChange(of: selectedCheckpointRef) { checkpointRef in
                guard let componentID = componentID(for: checkpointRef) else {
                    return
                }
                withAnimation(.easeInOut(duration: 0.22)) {
                    proxy.scrollTo(componentID, anchor: .top)
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title.isEmpty ? reportTitle : title)
                .font(.largeTitle.weight(.bold))
            Text(L10n.format("由 %@ 负责 · 当前阶段：%@", profileName,
                             ResearchDisplayText.node(detail.currentNode)))
                .font(.callout)
                .foregroundStyle(.secondary)
            Text(L10n.text("研究节点进入后自动建立章节，正文和证据可在本地报告中继续补充。"))
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }

    @ViewBuilder
    private func chapterView(_ chapter: LocalReportComponent) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(chapter.title).font(.title2.weight(.semibold))
            if !chapter.body.isEmpty { Text(chapter.body) }
            ForEach(components.filter { $0.parentID == chapter.id }) { item in
                VStack(alignment: .leading, spacing: 5) {
                    Text(item.title).font(.headline)
                    if !item.body.isEmpty { Text(item.body) }
                    if !item.content.isEmpty {
                        Text(item.content).font(.system(.body, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.leading, 14)
            }
        }
        .id(chapter.id)
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.secondary.opacity(0.045),
                    in: RoundedRectangle(cornerRadius: 14))
    }

    private func load() async {
        guard let url = URL(string: artifact.localRef), url.isFileURL else {
            error = L10n.text("本地报告路径无效")
            return
        }
        do {
            let (loadedTitle, loadedComponents) = try await Task.detached {
                let data = try PersonalWorkspaceAccessStore.withAccess(to: url) {
                    try Data(contentsOf: url)
                }
                guard let root = try JSONSerialization.jsonObject(
                    with: data
                ) as? [String: Any] else { throw ReportDocumentError.invalid }
                let values = (root["components"] as? [[String: Any]] ?? []).compactMap {
                    Self.component($0)
                }
                return (root["title"] as? String ?? "", values)
            }.value
            title = loadedTitle
            components = loadedComponents
            error = nil
            if selectedCheckpointRef.isEmpty {
                selectedCheckpointRef = detail.latestTraceRef
                    ?? navigationSectionRefs.keys.sorted().first
                    ?? (detail.currentNode.isEmpty
                        ? "" : "node:\(detail.currentNode)")
            }
        } catch {
            self.error = L10n.text("本地研究报告无法读取")
        }
    }

    private var navigationSectionRefs: [String: String] {
        Dictionary(
            artifact.sectionRefs.map { ($0.targetRef, $0.sectionRef) },
            uniquingKeysWith: { first, _ in first }
        )
    }

    private func selectCheckpoint(
        _ checkpointRef: String,
        _ branchID: String
    ) {
        if ResearchBranchNavigation.requiresReload(
            currentBranchRef: detail.branchRef,
            targetBranchID: branchID
        ) {
            selectBranch(branchID)
        }
        selectedCheckpointRef = checkpointRef
    }

    private func componentID(for checkpointRef: String) -> String? {
        if let componentID = navigationSectionRefs[checkpointRef] {
            return componentID
        }
        if let step = steps.first(where: { $0.stepRef == checkpointRef }) {
            return navigationSectionRefs["node:\(step.toNode)"]
        }
        if let node = workPackage.tree?.nodes.first(where: {
            $0.checkpointRef == checkpointRef
        }) {
            return navigationSectionRefs["node:\(node.toNode)"]
        }
        return nil
    }

    private static func component(
        _ value: [String: Any]
    ) -> LocalReportComponent? {
        guard let id = value["component_id"] as? String,
              let kind = value["kind"] as? String,
              let title = value["title"] as? String else { return nil }
        var content = ""
        if let object = value["content"] {
            if let dict = object as? [String: Any], let code = dict["code"] as? String {
                content = code
            } else if let dict = object as? [String: Any], let latex = dict["latex"] as? String {
                content = latex
            } else if JSONSerialization.isValidJSONObject(object),
                      let data = try? JSONSerialization.data(withJSONObject: object),
                      let text = String(data: data, encoding: .utf8) {
                content = text
            }
        }
        return LocalReportComponent(
            id: id, kind: kind, parentID: value["parent_id"] as? String,
            title: title, body: value["body"] as? String ?? "", content: content
        )
    }
}

private enum ReportDocumentError: Error { case invalid }
