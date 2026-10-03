import SwiftUI

struct ClientTabView: View {
    @EnvironmentObject private var session: SessionStore
    let tab: ClientTab
    @ObservedObject var profiles: LocalProfileController
    @ObservedObject var tabSession: ClientTabSession
    let open: (ClientTab) -> Void
    let isActive: Bool

    var body: some View {
        content
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
        let local = !request.profileRef.isEmpty
            && profiles.profiles.contains { $0.id == request.profileRef }
        if local, !request.reportWorkspaceID.isEmpty, !request.branchID.isEmpty {
            Task { @MainActor in
                do {
                    try await ResearchReportExportController.export(
                        format: request.format,
                        profileID: request.profileRef,
                        reportWorkspaceID: request.reportWorkspaceID,
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

    /// The manager renders Markdown from the report it holds; PDF is a client
    /// renderer, so a report that is not on this machine still needs the client.
    private func openServerExport(_ request: ResearchReportExportMessage.Request) {
        guard let base = ManagerConfig.shared.baseURL,
              let url = request.serverExportURL(relativeTo: base) else { return }
        open(.externalWeb(url))
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
