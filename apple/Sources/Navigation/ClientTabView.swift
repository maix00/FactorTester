import SwiftUI

struct ClientTabView: View {
    @EnvironmentObject private var session: SessionStore
    let tab: ClientTab
    @ObservedObject var profiles: LocalProfileController
    @ObservedObject var tabSession: ClientTabSession
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
        case .module(let module):
            ModuleDestinationView(
                module: module,
                webPageSession: tabSession.ensureWebPageSession(),
                onReference: openReference,
                onNavigation: openEmbeddedNavigation,
                onExternalURL: { open(.externalWeb($0)) }
            )
        case .adapter(let adapter):
            if let url = adapter.uiURL {
                LocalAdapterWebView(
                    title: adapter.displayName,
                    url: url,
                    webPageSession: tabSession.ensureWebPageSession()
                )
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
            WebPageView(
                path: path,
                webSession: tabSession.ensureWebPageSession(),
                onReference: { reference in
                    openReference(reference)
                },
                onNavigation: openEmbeddedNavigation,
                onExternalURL: { open(.externalWeb($0)) },
                onReportExport: handleReportExport
            )
        case .externalWeb(let url):
            WebPageView(
                path: "",
                externalURL: url,
                webSession: tabSession.ensureWebPageSession(),
                onReference: { openReference($0) },
                onExternalURL: { open(.externalWeb($0)) }
            )
        case .research:
            ResearchModuleView(
                tabSession: tabSession,
                openReferencePage: openReference,
                // The research shell owns its local/shared/graph switcher.
                // Section changes update this pinned tab's lightweight
                // session; only a concrete /research/<ref> report opens a
                // dedicated tab.
                openResearchPath: openEmbeddedNavigation,
                openExternalURL: { open(.externalWeb($0)) }
            )
        case .jobs:
            WebPageView(
                path: "/jobs?section=types",
                webSession: tabSession.ensureWebPageSession(),
                onReference: openReference,
                onNavigation: openEmbeddedNavigation,
                onExternalURL: { open(.externalWeb($0)) }
            )
        case .testJob(let job):
            WebPageView(
                path: ClientTab.jobPath(job),
                webSession: tabSession.ensureWebPageSession(),
                onReference: openReference,
                onNavigation: openEmbeddedNavigation,
                onExternalURL: { open(.externalWeb($0)) }
            )
        case .workPackage(let item):
            workPackage(item)
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

    /// Export a report requested from the embedded report page.  A report whose
    /// profile is local (this machine holds its tree) exports through the
    /// native renderer; otherwise fall back to the manager's Markdown export.
    private func handleReportExport(_ request: ResearchReportExportMessage.Request) {
        #if os(macOS)
        let local = profiles.profiles.contains { $0.id == request.profileID }
        if local, !request.workPackageID.isEmpty, !request.branchID.isEmpty {
            Task { @MainActor in
                do {
                    try await ResearchReportExportController.export(
                        format: request.format,
                        profileID: request.profileID,
                        workPackageID: request.workPackageID,
                        branchID: request.branchID,
                        title: request.title
                    )
                    return
                } catch {
                    openServerExport(request)
                }
            }
            return
        }
        #endif
        openServerExport(request)
    }

    /// The manager renders Markdown from the report tree it holds; PDF is not
    /// available server-side, so a remote PDF relies on the client renderer.
    private func openServerExport(_ request: ResearchReportExportMessage.Request) {
        guard let base = ManagerConfig.shared.baseURL,
              var components = URLComponents(
                url: base, resolvingAgainstBaseURL: false,
              ) else { return }
        components.path = "/api/server-research/\(request.serverRef)/export"
        components.queryItems = [
            URLQueryItem(name: "format", value: request.format.rawValue),
        ]
        if !request.targetRef.isEmpty {
            components.queryItems?.append(
                URLQueryItem(name: "target_ref", value: request.targetRef),
            )
        }
        guard let url = components.url else { return }
        open(.externalWeb(url))
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
                tabSession: tabSession,
                openJob: { open(.testJob($0)) },
                openProfile: {
                    open(.profile(id: $0, title: $1))
                },
                openReferencePage: {
                    openReference($0)
                },
                openExternalURL: { open(.externalWeb($0)) },
                openResearchPath: { path in
                    open(.researchReport(path: path))
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

    private func openReference(_ reference: ResearchDocumentTypedLink) {
        guard let destination = ClientTab.reference(reference) else { return }
        open(destination)
    }

    private func openEmbeddedNavigation(_ path: String) {
        if let section = ResearchModuleSection.fromResearchPath(path) {
            tabSession.researchSection = section
        } else if let destination = ClientTab.embeddedNavigationDestination(
            for: path,
            sourceServicePort: tab.servicePort
        ) {
            open(destination)
        }
    }
}

enum ResearchSessionAccess {
    static func canLoad(user: UserInfo?) -> Bool {
        user?.isLoggedIn == true
    }
}
