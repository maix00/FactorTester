import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var session: SessionStore
    @EnvironmentObject private var registry: ModuleRegistry
    @EnvironmentObject private var config: ServerConfig

    @StateObject private var profiles = LocalProfileController()
    @StateObject private var tabSessions = ClientTabSessionStore()
    @StateObject private var workspaceAuthorization =
        PersonalWorkspaceAuthorizationCoordinator()
    @State private var tabs: [ClientTab] = [.home]
    @State private var selection = ClientTab.home.id
    @State private var showLogin = false
    @State private var pendingModule: Module?
    @State private var managerNetworkInfo: ManagerNetworkInfo?
    @State private var managerNetworkError: String?

    var body: some View {
        NavigationSplitView {
            ClientSidebar(
                selection: sidebarSelection,
                openTabs: tabs,
                open: open,
                close: close
            )
        } detail: {
            Group {
                if selection == ClientTab.home.id {
                    dashboard
                } else if let selectedTab {
                    ClientTabView(
                        tab: selectedTab,
                        profiles: profiles,
                        tabSession: tabSessions.session(for: selectedTab.id),
                        open: open,
                        isActive: true
                    )
                    .id(selectedTab.id)
                } else {
                    dashboard
                }
            }
            .navigationTitle(selectedTab?.localizedTitle ?? ClientTab.home.localizedTitle)
        }
        .onChange(of: selection) { tabID in
            tabSessions.activate(tabID)
        }
        .sheet(isPresented: $showLogin) { loginSheet }
        .alert(
            L10n.text("个人工作区"),
            isPresented: Binding(
                get: { workspaceAuthorization.errorMessage != nil },
                set: { if !$0 { workspaceAuthorization.clearError() } }
            )
        ) {
            Button(L10n.text("知道了")) {
                workspaceAuthorization.clearError()
            }
        } message: {
            Text(workspaceAuthorization.errorMessage ?? "")
        }
        .task {
            async let sessionRefresh = session.refresh()
            async let moduleReload: Void = registry.reload()
            async let profileRefresh: Void = profiles.refresh()
            async let networkRefresh: Void = refreshManagerNetworkInfo()
            _ = await (
                sessionRefresh,
                moduleReload,
                profileRefresh,
                networkRefresh
            )
        }
        .task(id: workspaceAuthorizationPrincipal) {
            guard !workspaceAuthorizationPrincipal.isEmpty else { return }
            await Task.yield()
            workspaceAuthorization.requestIfNeeded(
                principal: workspaceAuthorizationPrincipal
            )
        }
    }

    private var dashboard: some View {
        HomeDashboardView(
            modules: registry.visibleModules(forRole: session.role).filter {
                $0.id != "server_operations"
            },
            showManager: session.role == "super_admin",
            isLoading: registry.isLoading,
            loadError: registry.loadError,
            networkInfo: managerNetworkInfo,
            networkError: managerNetworkError,
            openModule: tap,
            openAdapter: { open(.adapter($0)) },
            openTab: open
        )
    }

    private var loginSheet: some View {
        LoginView { didLogin in
            showLogin = false
            if didLogin, let module = pendingModule {
                open(.module(module))
            }
            pendingModule = nil
        }
        .environmentObject(session)
    }

    private func tap(_ module: Module) {
        if module.requiresAuth && !session.isLoggedIn {
            pendingModule = module
            showLogin = true
        } else {
            open(.module(module))
        }
    }

    private func open(_ tab: ClientTab) {
        if !tabs.contains(where: { $0.id == tab.id }) {
            tabs.append(tab)
        }
        selection = tab.id
    }

    private var sidebarSelection: Binding<String> {
        Binding(
            get: { selection },
            set: { id in
                ClientTabSelectionRouter(
                    tabs: { tabs },
                    setTabs: { tabs = $0 },
                    setSelection: { selection = $0 }
                ).select(id)
            }
        )
    }

    private func close(_ tab: ClientTab) {
        guard tab.isClosable else { return }
        tabs.removeAll { $0.id == tab.id }
        tabSessions.removeSession(for: tab.id)
        if selection == tab.id { selection = ClientTab.home.id }
    }

    private var selectedTab: ClientTab? {
        tabs.first { $0.id == selection }
    }

    private var workspaceAuthorizationPrincipal: String {
        guard !session.isWorking, session.isLoggedIn else { return "" }
        return session.user?.username ?? ""
    }

    @MainActor
    private func refreshManagerNetworkInfo() async {
        do {
            managerNetworkInfo = try await ManagerNetworkInfoService.shared.fetch()
            managerNetworkError = nil
        } catch {
            managerNetworkInfo = nil
            managerNetworkError = error.localizedDescription
        }
    }
}
