import SwiftUI
import UniformTypeIdentifiers

struct ResearchModuleView: View {
    @ObservedObject var tabSession: ClientTabSession
    let openReferencePage: (ResearchDocumentTypedLink) -> Void
    let openResearchPath: (String) -> Void
    let openExternalURL: (URL) -> Void
    @StateObject private var localGraphs = LocalResearchGraphStore()
    @State private var showingGraphImporter = false

    var body: some View {
        // The server Graph tabs remain Web-rendered.  Local YAML is deliberately
        // a Swift-owned store so importing it cannot silently upload to a
        // Manager or become mixed with the server presentation tabs.
        VStack(spacing: 10) {
            if tabSession.researchSection == .graph {
                LocalResearchGraphPanel(
                    store: localGraphs,
                    importFile: { showingGraphImporter = true }
                )
                .padding(.horizontal, 10)
            }
            WebPageView(
                path: researchPath,
                webSession: tabSession.ensureWebPageSession(),
                onReference: openReferencePage,
                onNavigation: openResearchPath,
                onExternalURL: openExternalURL
            )
        }
        .fileImporter(
            isPresented: $showingGraphImporter,
            allowedContentTypes: [
                UTType(filenameExtension: "yaml") ?? .data,
                UTType(filenameExtension: "yml") ?? .data,
            ],
            allowsMultipleSelection: false
        ) { result in
            if case .success(let urls) = result, let url = urls.first {
                localGraphs.importFile(from: url)
            }
        }
    }

    private var researchPath: String {
        "/research?section=\(tabSession.researchSection.rawValue)"
    }
}
