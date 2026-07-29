import Foundation
import SwiftUI

struct ResearchDocumentReportView: View {
    let detail: ProfileResearchDetail
    let workPackage: ProfileResearchWorkPackageDetail
    let steps: [ResearchTransitionStep]
    let profileName: String
    let reportTitle: String
    let artifact: ResearchArtifactModel
    let serverURL: URL
    let openJob: (TestJob) -> Void

    @StateObject private var observer: ResearchReportTreeFileObserver
    @State private var title = ""
    @State private var components: [ResearchDocumentComponent] = []
    @State private var assets: [ResearchDocumentAsset] = []
    @State private var bindings: [ResearchDocumentBinding] = []
    @State private var error: String?
    @State private var selectedComponentID = ""
    @State private var windowCenterID = ""
    @State private var scrollRequestID = ""
    @State private var outlineIDs: [String] = []
    @State private var presentedReference: ResearchDocumentTypedLink?

    init(
        detail: ProfileResearchDetail,
        workPackage: ProfileResearchWorkPackageDetail,
        steps: [ResearchTransitionStep],
        profileName: String,
        reportTitle: String,
        artifact: ResearchArtifactModel,
        serverURL: URL,
        openJob: @escaping (TestJob) -> Void
    ) {
        self.detail = detail
        self.workPackage = workPackage
        self.steps = steps
        self.profileName = profileName
        self.reportTitle = reportTitle
        self.artifact = artifact
        self.serverURL = serverURL
        self.openJob = openJob
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
                scrollTarget: scrollRequestID,
                visibleChapter: selectVisibleChapter
            )
        }
        .task(id: "\(artifact.localRef)|\(observer.revision)|\(windowCenterID)") {
            await loadFocusedReport()
        }
        .environment(\.researchDocumentReferenceAction, openReference)
        .sheet(item: $presentedReference) { reference in
            ResearchDocumentReferenceOverlay(
                reference: reference,
                binding: matchingBinding(reference),
                asset: matchingAsset(reference),
                reportRef: artifact.localRef,
                serverURL: serverURL,
                objectHref: ResearchDocumentReferenceRouter.cycleObjectHref(
                    for: reference,
                    steps: steps
                )
            )
        }
        .onAppear { observer.start() }
        .onDisappear { observer.stop() }
    }

    private func loadFocusedReport() async {
        do {
            if windowCenterID.isEmpty, let initial = initialComponentID {
                windowCenterID = initial
                scrollRequestID = initial
                return
            }
            let payload = try await ResearchReportTreeSource.load(
                localRef: artifact.localRef,
                focusedComponentID: windowCenterID.isEmpty ? nil : windowCenterID,
                windowRadius: 1
            )
            try Task.checkCancellation()
            let nextHead = ResearchReportHeadFollow.nextChapter(
                previousOutline: outlineIDs,
                selectedID: selectedComponentID,
                centeredID: windowCenterID,
                newOutline: payload.outlineIDs
            )
            title = payload.title
            components = payload.components
            assets = payload.assets
            bindings = payload.bindings
            outlineIDs = payload.outlineIDs
            error = nil
            if let nextHead {
                selectedComponentID = nextHead
                windowCenterID = nextHead
                scrollRequestID = nextHead
                return
            }
            selectedComponentID = payload.focusedComponentID ?? ""
            if windowCenterID != (payload.focusedComponentID ?? "") {
                windowCenterID = payload.focusedComponentID ?? ""
                if scrollRequestID.isEmpty {
                    scrollRequestID = windowCenterID
                }
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
        windowCenterID = item.componentID
        scrollRequestID = item.componentID
    }

    private func selectVisibleChapter(_ componentID: String) {
        guard !componentID.isEmpty, componentID != selectedComponentID else { return }
        selectedComponentID = componentID
        windowCenterID = componentID
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

    private func openReference(_ reference: ResearchDocumentTypedLink) {
        if let jobID = ResearchDocumentReferenceRouter.jobID(from: reference) {
            openJob(TestJob(
                id: jobID,
                kind: "test",
                status: "unknown",
                workspaceID: "",
                port: serverURL.port ?? 0,
                profile: profileName,
                updatedAt: nil,
                artifactCount: 0
            ))
            return
        }
        presentedReference = reference
    }

    private func matchingBinding(
        _ reference: ResearchDocumentTypedLink
    ) -> ResearchDocumentBinding? {
        bindings.first {
            $0.kind == reference.kind && $0.targetRef == reference.targetRef
        }
    }

    private func matchingAsset(
        _ reference: ResearchDocumentTypedLink
    ) -> ResearchDocumentAsset? {
        guard reference.kind == "artifact" else { return nil }
        return assets.first {
            $0.assetRef == reference.targetRef
                || $0.externalRef == reference.targetRef
                || $0.filename == reference.targetRef
        }
    }
}
