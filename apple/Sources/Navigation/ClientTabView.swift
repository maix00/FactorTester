import SwiftUI

struct ClientTabView: View {
    let tab: ClientTab
    @ObservedObject var profiles: LocalProfileController
    let open: (ClientTab) -> Void
    let isActive: Bool

    var body: some View {
        content
    }

    @ViewBuilder
    private var content: some View {
        switch tab.content {
        case .home:
            EmptyView()
        case .module(let module):
            ModuleDestinationView(module: module)
        case .adapter(let adapter):
            if let url = adapter.uiURL {
                LocalAdapterWebView(title: adapter.displayName, url: url)
            } else {
                VStack(spacing: 10) {
                    Image(systemName: "network.slash")
                        .font(.largeTitle)
                    Text("无法打开").font(.headline)
                    Text("该组件没有声明可嵌入的本地 Web UI。")
                        .foregroundStyle(.secondary)
                }
            }
        case .web(let path):
            WebPageView(path: path)
        case .research:
            ProfileResearchOverview(
                profiles: profiles.profiles,
                openWorkPackage: { open(.workPackage($0)) }
            )
        case .workPackage(let item):
            let visibleProfiles = profiles.profiles.filter {
                item.profileIDs.contains($0.id)
            }
            if visibleProfiles.count == 1,
               let primaryProfile = visibleProfiles.first {
                WorkPackageResearchView(
                    item: item,
                    profiles: visibleProfiles,
                    primaryProfile: primaryProfile,
                    isActive: isActive,
                    onCheckpointChange: { checkpointRef in
                        Task {
                            await profiles.refreshUntilCheckpoint(
                                profileID: primaryProfile.id,
                                checkpointRef: checkpointRef
                            )
                        }
                    }
                )
            } else {
                VStack(spacing: 10) {
                    Image(systemName: "person.crop.circle.badge.questionmark")
                        .font(.largeTitle)
                    Text("研究 Profile 不可用").font(.headline)
                    Text("该 Work Package 没有唯一且可验证的本地 Profile 归属。")
                        .foregroundStyle(.secondary)
                }
            }
        case .profiles:
            ProfilesDirectoryView(
                controller: profiles,
                openProfile: { open(.profile(id: $0.id, title: $0.displayName)) }
            )
        case .profile(let id):
            if let profile = profiles.profiles.first(where: { $0.id == id }) {
                ProfileWorkspaceView(profile: profile)
            } else {
                VStack(spacing: 10) {
                    Image(systemName: "person.crop.circle.badge.questionmark")
                        .font(.largeTitle)
                    Text("Profile 不可用").font(.headline)
                    Text("该 Profile 已被移除或尚未从本地注册表加载。")
                        .foregroundStyle(.secondary)
                }
            }
        case .account:
            AccountCenterView(open: open)
        case .settings:
            ClientSettingsHub(open: open)
        }
    }
}
