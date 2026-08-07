import SwiftUI

/// Full-tab counterpart of the report reference sheet.  Web-rendered
/// reports send every typed link back through the Swift tab stack; this view
/// keeps the existing structured reference renderer instead of silently
/// dropping kinds that do not have a dedicated module page yet.
struct ResearchDocumentReferenceTabView: View {
    let reference: ResearchDocumentTypedLink
    let openJob: (TestJob) -> Void

    private var serviceURL: URL {
        ManagerConfig.shared.baseURL
            ?? ServerConfig.shared.baseURL
            ?? URL(string: "http://127.0.0.1:8141")!
    }

    var body: some View {
        ResearchDocumentReferenceOverlay(
            reference: reference,
            binding: nil,
            asset: nil,
            reportRef: "",
            serverURL: serviceURL,
            objectHref: nil,
            openJobSource: { jobID, port in
                openJob(TestJob(
                    id: jobID,
                    kind: "test",
                    status: "unknown",
                    workspaceID: "",
                    port: port,
                    profile: "",
                    updatedAt: nil,
                    artifactCount: 0
                ))
            },
            showsDismiss: false
        )
    }
}
