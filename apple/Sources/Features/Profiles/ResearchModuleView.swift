import SwiftUI

struct ResearchModuleView: View {
    @ObservedObject var tabSession: ClientTabSession
    let openReferencePage: (ResearchDocumentTypedLink) -> Void
    let openResearchPath: (String) -> Void
    let openExternalURL: (URL) -> Void

    var body: some View {
        VStack(spacing: 0) {
            Picker("研究页面", selection: $tabSession.researchSection) {
                ForEach(ResearchModuleSection.allCases) { value in
                    Text(verbatim: value.title).tag(value)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 280)
            .padding(.top, 16)
            .padding(.horizontal, 24)

            WebPageView(
                path: researchPath,
                webSession: tabSession.ensureWebPageSession(),
                onReference: openReferencePage,
                onNavigation: openResearchPath,
                onExternalURL: openExternalURL
            )
        }
    }

    private var researchPath: String {
        "/research?section=\(tabSession.researchSection.rawValue)"
    }
}

private extension ResearchModuleSection {
    var title: String {
        switch self {
        case .local: return L10n.text("本地研究")
        case .shared: return L10n.text("共享研究")
        case .graph: return L10n.text("研究图")
        }
    }
}
