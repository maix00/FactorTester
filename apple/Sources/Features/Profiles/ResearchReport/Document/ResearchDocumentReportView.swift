import Foundation
import SwiftUI
#if os(macOS)
import AppKit
#endif

struct ResearchDocumentReportView: View {
    let detail: ProfileResearchDetail
    let workPackage: ProfileResearchWorkPackageDetail
    let steps: [ResearchTransitionStep]
    let profileID: String
    let profileName: String
    let reportTitle: String
    let artifact: ResearchArtifactModel
    let serverURL: URL
    let tabSession: ResearchReportTabSession
    let openJob: (TestJob) -> Void
    let openProfile: (String, String) -> Void
    let openReferencePage: (ResearchDocumentTypedLink) -> Void

    @StateObject var observer: ResearchReportTreeFileObserver
    @StateObject var scrollAnchorCoordinator =
        ResearchReportScrollAnchorCoordinator()
    @State var document = ResearchReportLoadedDocument()
    @State var error: String?
    @State var selectedComponentID = ""
    @State var pendingComponentID = ""
    @State var scrollRequest: ResearchReportScrollRequest?
    @State var scrollToken = 0
    @State var loadToken = 0
    @State var chapterLoadTask: Task<Void, Never>?
    @State var appliedGraphNavigationID = ""
    @State private var presentedReference: ResearchDocumentTypedLink?
    @State var hasLoadedReport = false
    #if os(macOS)
    @StateObject private var selectionCoordinator =
        ResearchDocumentSelectionCoordinator()
    #endif

    init(
        detail: ProfileResearchDetail,
        workPackage: ProfileResearchWorkPackageDetail,
        steps: [ResearchTransitionStep],
        profileID: String,
        profileName: String,
        reportTitle: String,
        artifact: ResearchArtifactModel,
        serverURL: URL,
        tabSession: ResearchReportTabSession,
        openJob: @escaping (TestJob) -> Void,
        openProfile: @escaping (String, String) -> Void,
        openReferencePage: @escaping (ResearchDocumentTypedLink) -> Void = { _ in }
    ) {
        self.detail = detail
        self.workPackage = workPackage
        self.steps = steps
        self.profileID = profileID
        self.profileName = profileName
        self.reportTitle = reportTitle
        self.artifact = artifact
        self.serverURL = serverURL
        self.tabSession = tabSession
        self.openJob = openJob
        self.openProfile = openProfile
        self.openReferencePage = openReferencePage
        _selectedComponentID = State(
            initialValue: tabSession.selectedChapterID
        )
        _appliedGraphNavigationID = State(
            initialValue: tabSession.appliedGraphNavigationID
        )
        _observer = StateObject(wrappedValue: ResearchReportTreeFileObserver(
            localRef: artifact.localRef
        ))
    }

    var body: some View {
        ZStack(alignment: .leading) {
            ResearchReportTreePage(
                title: ResearchReportPageTitle.resolve(
                    selectedChapterID: selectedComponentID,
                    components: document.components,
                    currentNode: detail.currentNode
                ),
                error: error,
                isLoading: !hasLoadedReport,
                components: document.components,
                assets: document.assets,
                bindings: document.bindings,
                chapterOrder: document.outlineIDs,
                reportRef: artifact.localRef,
                scrollRequest: scrollRequest,
                scrollAnchorCoordinator: scrollAnchorCoordinator,
                pageBoundary: selectAdjacentChapter,
                canPageBoundary: canSelectAdjacentChapter
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
        .task(
            id: "\(artifact.localRef)|\(observer.revision)|\(graphNavigationID)"
        ) {
            await reloadReport()
        }
        .environment(\.researchDocumentReferenceAction, openReference)
        #if os(macOS)
        .environment(
            \.researchDocumentSelectionCoordinator,
            selectionCoordinator
        )
        #endif
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
                ),
                openJobSource: { jobID, port, serverID in
                    if serverID.isEmpty {
                        openJob(TestJob(
                            id: jobID,
                            kind: "test",
                            status: "unknown",
                            workspaceID: "",
                            port: port ?? serverURL.port
                                ?? ManagerConfig.bakedPublicBootstrapEndpoint.port
                                ?? 7998,
                            profile: profileName,
                            updatedAt: nil,
                            artifactCount: 0
                        ))
                    } else {
                        var detailFields = [
                            ResearchDocumentReferenceField(
                                name: "server_id", value: serverID
                            ),
                        ]
                        if let port {
                            detailFields.append(.init(
                                name: "port", value: String(port)
                            ))
                        }
                        openReferencePage(.init(
                            kind: "job",
                            targetRef: "job:\(jobID)",
                            label: L10n.text("测试任务"),
                            detailFields: detailFields
                        ))
                    }
                }
            )
        }
        .onAppear {
            observer.start()
            #if os(macOS)
            selectionCoordinator.start()
            #endif
        }
        .onDisappear {
            persistTabSession()
            observer.stop()
            chapterLoadTask?.cancel()
            chapterLoadTask = nil
            loadToken &+= 1
            #if os(macOS)
            selectionCoordinator.stop()
            #endif
        }
    }

    private func persistTabSession() {
        if let generation = document.generation {
            tabSession.generation = generation
        }
        tabSession.selectedChapterID = selectedComponentID
        tabSession.appliedGraphNavigationID = appliedGraphNavigationID
    }

    private func openReference(_ reference: ResearchDocumentTypedLink) {
        if let webURL = ResearchDocumentReferenceRouter.webURL(for: reference) {
            #if os(macOS)
            ResearchDocumentExternalURLLauncher.open(webURL)
            #endif
            return
        }
        if let fileURL = ResearchDocumentReferenceRouter.localFileURL(
            for: reference, reportRef: artifact.localRef
        ) {
            #if os(macOS)
            _ = try? PersonalWorkspaceAccessStore.withAccess(to: fileURL) {
                ResearchDocumentExternalURLLauncher.open(fileURL)
            }
            #endif
            return
        }
        let binding = matchingBinding(reference)
        if let profileID = ResearchDocumentReferenceBindingResolver.profileID(
            for: reference, binding: binding
        ) {
            openProfile(profileID, reference.label)
            return
        }
        if let route = ResearchDocumentReferenceBindingResolver.jobRoute(
            for: reference, binding: binding
        ), route.serverID.isEmpty, let port = route.port {
            openJob(TestJob(
                id: route.jobID,
                kind: "test",
                status: "unknown",
                workspaceID: "",
                port: port,
                profile: profileName,
                updatedAt: nil,
                artifactCount: 0
            ))
            return
        }
        if ClientTab.reference(reference) != nil {
            openReferencePage(reference)
            return
        }
        presentedReference = reference
    }

    private func matchingBinding(
        _ reference: ResearchDocumentTypedLink
    ) -> ResearchDocumentBinding? {
        ResearchDocumentReferenceBindingResolver.binding(
            for: reference, in: document.bindings
        )
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
