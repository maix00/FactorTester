import Foundation
import SwiftUI
#if os(macOS)
import AppKit
#endif

struct ResearchDocumentReportView: View {
    let detail: ProfileResearchDetail
    let workPackage: ProfileResearchWorkPackageDetail
    let steps: [ResearchTransitionStep]
    let profileName: String
    let reportTitle: String
    let artifact: ResearchArtifactModel
    let serverURL: URL
    let openJob: (TestJob) -> Void

    @StateObject var observer: ResearchReportTreeFileObserver
    @State var document = ResearchReportLoadedDocument()
    @State var error: String?
    @State var selectedComponentID = ""
    @State var pendingComponentID = ""
    @State var scrollRequest: ResearchReportScrollRequest?
    @State var scrollToken = 0
    @State var loadToken = 0
    @State private var presentedReference: ResearchDocumentTypedLink?
    @State var hasLoadedReport = false

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
        ZStack(alignment: .leading) {
            ResearchReportTreePage(
                title: document.title.isEmpty ? reportTitle : document.title,
                profileName: profileName,
                currentNode: detail.currentNode,
                error: error,
                isLoading: !hasLoadedReport,
                components: document.components,
                assets: document.assets,
                bindings: document.bindings,
                chapterOrder: document.outlineIDs,
                reportRef: artifact.localRef,
                scrollRequest: scrollRequest,
                visibleChapter: selectVisibleChapter
            )
            ResearchReportNodeTimelineNavigator(
                items: timelineItems,
                selectedComponentID: $selectedComponentID,
                pendingComponentID: $pendingComponentID,
                select: selectTimelineItem
            )
            .padding(.leading, 8)
            .zIndex(10)
        }
        .task(id: "\(artifact.localRef)|\(observer.revision)") {
            await reloadReport()
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
        .onDisappear {
            observer.stop()
            loadToken &+= 1
        }
    }

    private func openReference(_ reference: ResearchDocumentTypedLink) {
        if let webURL = ResearchDocumentReferenceRouter.webURL(for: reference) {
            #if os(macOS)
            NSWorkspace.shared.open(webURL)
            #endif
            return
        }
        if let fileURL = ResearchDocumentReferenceRouter.localFileURL(
            for: reference, reportRef: artifact.localRef
        ) {
            #if os(macOS)
            _ = try? PersonalWorkspaceAccessStore.withAccess(to: fileURL) {
                NSWorkspace.shared.open(fileURL)
            }
            #endif
            return
        }
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
        document.bindings.first {
            $0.kind == reference.kind && $0.targetRef == reference.targetRef
        }
    }

    private func matchingAsset(
        _ reference: ResearchDocumentTypedLink
    ) -> ResearchDocumentAsset? {
        guard reference.kind == "artifact" else { return nil }
        return document.assets.first {
            $0.assetRef == reference.targetRef
                || $0.externalRef == reference.targetRef
                || $0.filename == reference.targetRef
        }
    }
}
