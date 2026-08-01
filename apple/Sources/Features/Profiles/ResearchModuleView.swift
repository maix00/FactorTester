import SwiftUI

struct ResearchModuleView: View {
    let profiles: [LocalProfileModel]
    let profileLoadState: LocalProfileLoadState
    let isActive: Bool
    @ObservedObject var tabSession: ClientTabSession
    let openWorkPackage: (ResearchDirectoryItem) -> Void

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
            case .progress:
                ProfileResearchOverview(
                    profiles: profiles,
                    profileLoadState: profileLoadState,
                    isActive: isActive,
                    lifecycle: $tabSession.researchLifecycle,
                    openWorkPackage: openWorkPackage
                )
            case .graph:
                ResearchGraphBrowserView(
                    profiles: profiles,
                    isActive: isActive,
                    tabSession: tabSession
                )
            }
        }
    }
}

private extension ResearchModuleSection {
    var title: String {
        switch self {
        case .progress: return L10n.text("研究进度")
        case .graph: return L10n.text("研究图")
        }
    }
}
