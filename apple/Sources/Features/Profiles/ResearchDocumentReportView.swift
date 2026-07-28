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

    @StateObject private var observer: ResearchReportTreeFileObserver
    @State private var title = ""
    @State private var components: [ResearchDocumentComponent] = []
    @State private var assets: [ResearchDocumentAsset] = []
    @State private var bindings: [ResearchDocumentBinding] = []
    @State private var error: String?
    @State private var selectedCheckpointRef = ""
    @State private var focusedComponentID = ""

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
        _observer = StateObject(wrappedValue: ResearchReportTreeFileObserver(
            localRef: artifact.localRef
        ))
    }

    var body: some View {
        HStack(spacing: 0) {
            ResearchVersionTreePane(
                detail: detail,
                workPackage: workPackage,
                steps: steps,
                sectionRefsByCheckpoint: ResearchReportTreeNavigation.sectionRefs(for: artifact),
                sectionRefsByNode: ResearchReportTreeNavigation.sectionRefs(for: artifact),
                selectedCheckpointRef: $selectedCheckpointRef,
                select: selectCheckpoint,
                loadEarlier: loadEarlier,
                canLoadEarlier: nextCursor != nil
            )
            .frame(width: ResearchTreeLayout.navigatorWidth)
            .clipped()
            Divider()
            ResearchReportTreePage(
                title: title.isEmpty ? reportTitle : title,
                profileName: profileName,
                currentNode: detail.currentNode,
                error: error,
                components: components,
                assets: assets,
                bindings: bindings,
                reportRef: artifact.localRef
            )
        }
        .task(id: "\(artifact.localRef)|\(observer.revision)|\(focusedComponentID)") {
            await loadFocusedReport()
        }
        .onAppear { observer.start() }
        .onDisappear { observer.stop() }
    }

    private func loadFocusedReport() async {
        do {
            if focusedComponentID.isEmpty, let initial = initialComponentID {
                focusedComponentID = initial
                return
            }
            let payload = try await ResearchReportTreeSource.load(
                localRef: artifact.localRef,
                focusedComponentID: focusedComponentID.isEmpty ? nil : focusedComponentID
            )
            try Task.checkCancellation()
            title = payload.title
            components = payload.components
            assets = payload.assets
            bindings = payload.bindings
            error = nil
            if selectedCheckpointRef.isEmpty {
                selectedCheckpointRef = detail.latestTraceRef
                    ?? artifact.sectionRefs.first?.targetRef
                    ?? (detail.currentNode.isEmpty ? "" : "node:\(detail.currentNode)")
            }
            if focusedComponentID != (payload.focusedComponentID ?? "") {
                focusedComponentID = payload.focusedComponentID ?? ""
                return
            }
            await ResearchReportTreeSource.prefetch(
                localRef: artifact.localRef,
                componentIDs: ResearchReportTreeNavigation.neighbors(
                    focused: focusedComponentID, outline: payload.outlineIDs
                )
            )
        } catch is CancellationError {
            return
        } catch {
            self.error = L10n.text("本地研究报告无法读取")
        }
    }

    private func selectCheckpoint(_ checkpointRef: String, _ branchID: String) {
        if ResearchBranchNavigation.requiresReload(currentBranchRef: detail.branchRef,
                                                     targetBranchID: branchID) {
            selectBranch(branchID)
        }
        selectedCheckpointRef = checkpointRef
        guard let componentID = ResearchReportTreeNavigation.componentID(
            for: checkpointRef, artifact: artifact, steps: steps,
            workPackage: workPackage
        ) else { return }
        withAnimation(.easeInOut(duration: 0.24)) {
            focusedComponentID = componentID
        }
    }

    private var initialComponentID: String? {
        let checkpoint = detail.latestTraceRef
            ?? (detail.currentNode.isEmpty ? "" : "node:\(detail.currentNode)")
        return ResearchReportTreeNavigation.componentID(
            for: checkpoint, artifact: artifact, steps: steps,
            workPackage: workPackage
        ) ?? artifact.sectionRefs.first?.sectionRef
    }
}
