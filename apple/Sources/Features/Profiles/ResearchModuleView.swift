import SwiftUI

struct ResearchModuleView: View {
    @ObservedObject var tabSession: ClientTabSession
    let openReferencePage: (ResearchDocumentTypedLink) -> Void
    let openResearchPath: (String) -> Void

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

            switch tabSession.researchSection {
            case .local:
                WebPageView(
                    path: "/research?section=local",
                    webSession: tabSession.ensureWebPageSession(),
                    onReference: openReferencePage,
                    onNavigation: openResearchPath
                )
            case .shared:
                WebPageView(
                    path: "/research?section=shared",
                    webSession: tabSession.ensureWebPageSession(),
                    onReference: openReferencePage,
                    onNavigation: openResearchPath
                )
            case .graph:
                WebPageView(
                    path: "/research?section=graph",
                    webSession: tabSession.ensureWebPageSession(),
                    onReference: openReferencePage,
                    onNavigation: openResearchPath
                )
            }
        }
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
