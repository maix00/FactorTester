import Foundation
import SwiftUI

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
    @State private var components: [ResearchDocumentComponent] = []
    @State private var assets: [ResearchDocumentAsset] = []
    @State private var error: String?
    @State private var sourceSignature = ""
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
            await watchReport()
        }
    }

    private var report: some View {
        ScrollViewReader { proxy in
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
                                children: children(of: component.id),
                                childrenByParent: childrenByParent,
                                assets: assets,
                                reportRef: artifact.localRef
                            )
                            .id(component.id)
                        }
                    }
                }
                .frame(maxWidth: 820, alignment: .leading)
                .padding(.horizontal, 42)
                .padding(.vertical, 34)
                .frame(maxWidth: .infinity, alignment: .center)
            }
            .onChange(of: selectedCheckpointRef) { checkpointRef in
                guard let componentID = componentID(for: checkpointRef) else { return }
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

    private func children(of id: String) -> [ResearchDocumentComponent] {
        childrenByParent[id] ?? []
    }

    private func watchReport() async {
        await load()
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard !Task.isCancelled,
                  let url = reportURL,
                  let signature = await Task.detached(operation: { Self.signature(for: url) }).value,
                  signature != sourceSignature else { continue }
            // Report writers may replace REPORT.json through several short
            // filesystem operations; wait for the final write before parsing.
            try? await Task.sleep(nanoseconds: 250_000_000)
            await load()
        }
    }

    private func load() async {
        guard let url = reportURL else {
            error = L10n.text("本地报告路径无效")
            return
        }
        do {
            let result = try await Task.detached {
                let data = try PersonalWorkspaceAccessStore.withAccess(to: url) {
                    try Data(contentsOf: url)
                }
                guard let root = try JSONSerialization.jsonObject(with: data)
                    as? [String: Any] else { throw ReportDocumentError.invalid }
                let values = (root["components"] as? [[String: Any]] ?? [])
                    .compactMap(ResearchDocumentParser.parseComponent)
                let assets = (root["assets"] as? [[String: Any]] ?? [])
                    .compactMap(ResearchDocumentParser.parseAsset)
                return (root["title"] as? String ?? "", values, assets,
                        Self.signature(for: url))
            }.value
            title = result.0
            components = result.1
            assets = result.2
            sourceSignature = result.3 ?? sourceSignature
            error = nil
            if selectedCheckpointRef.isEmpty {
                selectedCheckpointRef = detail.latestTraceRef
                    ?? navigationSectionRefs.keys.sorted().first
                    ?? (detail.currentNode.isEmpty ? "" : "node:\(detail.currentNode)")
            }
        } catch {
            self.error = L10n.text("本地研究报告无法读取")
        }
    }

    private var reportURL: URL? {
        guard let url = URL(string: artifact.localRef), url.isFileURL else { return nil }
        return url
    }

    private nonisolated static func signature(for url: URL) -> String? {
        guard let values = try? FileManager.default.attributesOfItem(atPath: url.path),
              let size = values[.size] as? NSNumber,
              let date = values[.modificationDate] as? Date else { return nil }
        return "\(size.int64Value):\(date.timeIntervalSince1970)"
    }

    private var navigationSectionRefs: [String: String] {
        Dictionary(artifact.sectionRefs.map { ($0.targetRef, $0.sectionRef) },
                   uniquingKeysWith: { first, _ in first })
    }

    private func selectCheckpoint(_ checkpointRef: String, _ branchID: String) {
        if ResearchBranchNavigation.requiresReload(currentBranchRef: detail.branchRef,
                                                     targetBranchID: branchID) {
            selectBranch(branchID)
        }
        selectedCheckpointRef = checkpointRef
    }

    private func componentID(for checkpointRef: String) -> String? {
        if let id = navigationSectionRefs[checkpointRef] { return id }
        if let step = steps.first(where: { $0.stepRef == checkpointRef }) {
            return navigationSectionRefs["node:\(step.toNode)"]
        }
        if let node = workPackage.tree?.nodes.first(where: { $0.checkpointRef == checkpointRef }) {
            return navigationSectionRefs["node:\(node.toNode)"]
        }
        return nil
    }
}

private enum ReportDocumentError: Error { case invalid }
