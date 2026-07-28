import Foundation
import SwiftUI

struct ResearchDocumentReportView: View {
    let detail: ProfileResearchDetail
    let workPackage: ProfileResearchWorkPackageDetail
    let steps: [ResearchTransitionStep]
    let profileName: String
    let reportTitle: String
    let artifact: ResearchArtifactModel

    @StateObject private var observer: ResearchReportTreeFileObserver
    @State private var title = ""
    @State private var components: [ResearchDocumentComponent] = []
    @State private var assets: [ResearchDocumentAsset] = []
    @State private var bindings: [ResearchDocumentBinding] = []
    @State private var error: String?
    @State private var selectedComponentID = ""
    @State private var focusedComponentID = ""
    @State private var outlineIDs: [String] = []

    init(
        detail: ProfileResearchDetail,
        workPackage: ProfileResearchWorkPackageDetail,
        steps: [ResearchTransitionStep],
        profileName: String,
        reportTitle: String,
        artifact: ResearchArtifactModel
    ) {
        self.detail = detail
        self.workPackage = workPackage
        self.steps = steps
        self.profileName = profileName
        self.reportTitle = reportTitle
        self.artifact = artifact
        _observer = StateObject(wrappedValue: ResearchReportTreeFileObserver(
            localRef: artifact.localRef
        ))
    }

    var body: some View {
        HStack(spacing: 0) {
            ResearchReportNodeTimelineNavigator(
                items: timelineItems,
                selectedComponentID: $selectedComponentID,
                select: selectTimelineItem
            )
            .frame(width: 220)
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
                reportRef: artifact.localRef,
                scrollTarget: focusedComponentID,
                visibleChapter: selectVisibleChapter
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
                focusedComponentID: focusedComponentID.isEmpty ? nil : focusedComponentID,
                windowRadius: 1
            )
            try Task.checkCancellation()
            title = payload.title
            components = payload.components
            assets = payload.assets
            bindings = payload.bindings
            outlineIDs = payload.outlineIDs
            error = nil
            selectedComponentID = payload.focusedComponentID ?? ""
            if focusedComponentID != (payload.focusedComponentID ?? "") {
                focusedComponentID = payload.focusedComponentID ?? ""
                return
            }
            await ResearchReportTreeSource.prefetch(
                localRef: artifact.localRef,
                componentIDs: ResearchReportChapterWindow.prefetchIDs(
                    outlineIDs: payload.outlineIDs,
                    loadedIDs: payload.loadedComponentIDs
                )
            )
        } catch is CancellationError {
            return
        } catch {
            self.error = L10n.text("本地研究报告无法读取")
        }
    }

    private func selectTimelineItem(_ item: ResearchReportNodeTimelineItem) {
        selectedComponentID = item.componentID
        withAnimation(.easeInOut(duration: 0.24)) {
            focusedComponentID = item.componentID
        }
    }

    private func selectVisibleChapter(_ componentID: String) {
        guard !componentID.isEmpty, componentID != selectedComponentID else { return }
        selectedComponentID = componentID
        Task {
            await ResearchReportTreeSource.prefetch(
                localRef: artifact.localRef,
                componentIDs: ResearchReportTreeNavigation.neighbors(
                    focused: componentID, outline: outlineIDs
                )
            )
        }
    }

    private var initialComponentID: String? {
        ResearchReportNodeTimelineBuilder.initialComponentID(
            detail: detail, workPackage: workPackage, steps: steps,
            artifact: artifact, items: timelineItems
        )
    }

    private var timelineItems: [ResearchReportNodeTimelineItem] {
        ResearchReportNodeTimelineBuilder.items(
            detail: detail, workPackage: workPackage, steps: steps, artifact: artifact
        )
    }
}
