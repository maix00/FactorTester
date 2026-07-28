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

    @StateObject private var observer: ResearchDocumentFileObserver
    @State private var title = ""
    @State private var components: [ResearchDocumentComponent] = []
    @State private var assets: [ResearchDocumentAsset] = []
    @State private var bindings: [ResearchDocumentBinding] = []
    @State private var error: String?
    @State private var selectedCheckpointRef = ""

    init(
        detail: ProfileResearchDetail,
        workPackage: ProfileResearchWorkPackageDetail,
        steps: [ResearchTransitionStep],
        nextCursor: String?,
        profileName: String,
        reportTitle: String,
        artifact: ResearchArtifactModel,
        selectBranch: @escaping (String) -> Void,
        loadEarlier: @escaping () async -> Void
    ) {
        self.detail = detail
        self.workPackage = workPackage
        self.steps = steps
        self.nextCursor = nextCursor
        self.profileName = profileName
        self.reportTitle = reportTitle
        self.artifact = artifact
        self.selectBranch = selectBranch
        self.loadEarlier = loadEarlier
        _observer = StateObject(wrappedValue: ResearchDocumentFileObserver(
            localRef: artifact.localRef
        ))
    }

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
        .task(id: "\(artifact.localRef)|\(observer.revision)") { await load() }
        .onAppear { observer.start() }
        .onDisappear { observer.stop() }
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
                                bindings: bindings,
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

    private func load() async {
        do {
            let payload = try await ResearchDocumentSource.load(
                localRef: artifact.localRef
            )
            title = payload.title
            components = payload.components
            assets = payload.assets
            bindings = payload.bindings
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
