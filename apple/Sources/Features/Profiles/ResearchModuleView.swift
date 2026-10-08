import SwiftUI

struct ResearchModuleView: View {
    @ObservedObject var tabSession: ClientTabSession
    let openReferencePage: (ResearchDocumentTypedLink) -> Void
    let openResearchPath: (String) -> Void
    let openExternalURL: (URL) -> Void
    var body: some View {
        WebPageView(
            path: researchPath,
            webSession: tabSession.ensureWebPageSession(),
            onReference: openReferencePage,
            onNavigation: openResearchPath,
            onExternalURL: openExternalURL
        )
    }

    private var researchPath: String {
        "/research?section=\(tabSession.researchSection.rawValue)"
    }
}
