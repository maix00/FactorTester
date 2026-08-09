import SwiftUI

struct ResearchModuleView: View {
    @ObservedObject var tabSession: ClientTabSession
    let openReferencePage: (ResearchDocumentTypedLink) -> Void
    let openResearchPath: (String) -> Void
    let openExternalURL: (URL) -> Void

    var body: some View {
        // The research entry is a Web-rendered page.  Keeping a native picker
        // here created two sources of truth: the Swift picker changed the URL
        // while the Web page owned its own section tabs.  The Web page now
        // renders the local/shared/graph switcher in its own toolbar; Swift
        // only owns the tab, session lifetime, and link routing.
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
