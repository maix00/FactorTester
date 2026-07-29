import SwiftUI

struct ClientTabView: View {
    @EnvironmentObject private var session: SessionStore
    let tab: ClientTab
    @ObservedObject var profiles: LocalProfileController
    let open: (ClientTab) -> Void
    let isActive: Bool
    @State private var showResearchLogin = false

    var body: some View {
        content
            .sheet(isPresented: $showResearchLogin) {
                LoginView { _ in showResearchLogin = false }
                    .environmentObject(session)
            }
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
            if ResearchSessionAccess.canLoad(user: session.user) {
                ProfileResearchOverview(
                    profiles: profiles.profiles,
                    profileLoadState: profiles.loadState,
                    isActive: isActive,
                    openWorkPackage: { open(.workPackage($0)) }
                )
            } else {
                researchLoginPrompt
            }
        case .jobs:
            TestJobsView(openJob: { open(.testJob($0)) })
        case .testJob(let job):
            TestJobDetailView(job: job)
        case .workPackage(let item):
            if ResearchSessionAccess.canLoad(user: session.user) {
                workPackage(item)
            } else {
                researchLoginPrompt
            }
        case .profiles:
            ProfilesDirectoryView(
                controller: profiles,
                openProfile: { open(.profile(id: $0.id, title: $0.displayName)) }
            )
        case .profile(let id):
            if profiles.profiles.isEmpty && profiles.loadState == .loading {
                ProgressView("正在读取本地 Profile…")
            } else if profiles.profiles.isEmpty && profiles.loadState == .failed {
                VStack(spacing: 10) {
                    Image(systemName: "exclamationmark.triangle")
                        .font(.largeTitle)
                    Text("本地 Profile 读取失败")
                        .font(.headline)
                    Text("暂不判断该 Profile 不存在，请稍后重试。")
                        .foregroundStyle(.secondary)
                }
            } else if let profile = profiles.profiles.first(where: { $0.id == id }) {
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
        case .accountSettings:
            ClientSettingsHub(open: open)
        case .manager:
            if session.role == "super_admin" && session.isManagerLoggedIn {
                ManagerView()
            } else {
                VStack(spacing: 10) {
                    Image(systemName: "lock.shield").font(.largeTitle)
                    Text("服务器管理不可用").font(.headline)
                    Text("需要超级管理员登录 Manager。")
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    @ViewBuilder
    private func workPackage(_ item: ResearchDirectoryItem) -> some View {
        let visibleProfiles = profiles.profiles.filter {
            item.profileIDs.contains($0.id)
        }
        if profiles.loadState == .loading && visibleProfiles.isEmpty {
            ProgressView("正在读取本地 Profile…")
        } else if profiles.loadState == .failed && visibleProfiles.isEmpty {
            VStack(spacing: 10) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.largeTitle)
                Text("本地 Profile 读取失败")
                    .font(.headline)
                Text("暂不判断该研究是否没有 Profile。")
                    .foregroundStyle(.secondary)
            }
        } else if visibleProfiles.count == 1,
                  let primaryProfile = visibleProfiles.first {
            WorkPackageResearchView(
                item: item,
                profiles: visibleProfiles,
                primaryProfile: primaryProfile,
                isActive: isActive,
                openJob: { open(.testJob($0)) },
                openProfile: {
                    open(.profile(id: $0, title: $1))
                },
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
    }

    private var researchLoginPrompt: some View {
        VStack(spacing: 12) {
            Image(systemName: "person.crop.circle.badge.xmark")
                .font(.largeTitle)
            Text("登录后读取研究").font(.headline)
            Text("当前会话无效；重新登录后将读取该工作区的 Work Packages。")
                .foregroundStyle(.secondary)
            Button("登录") { showResearchLogin = true }
                .buttonStyle(.borderedProminent)
        }
    }
}

enum ResearchSessionAccess {
    static func canLoad(user: UserInfo?) -> Bool {
        user?.isLoggedIn == true
    }
}
