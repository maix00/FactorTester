import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var session: SessionStore
    @EnvironmentObject private var registry: ModuleRegistry
    @EnvironmentObject private var config: ServerConfig

    @StateObject private var profiles = LocalProfileController()
    @StateObject private var tabSessions = ClientTabSessionStore()
    @State private var tabs: [ClientTab] = [.home]
    @State private var selection = ClientTab.home.id
    @State private var showLogin = false
    @State private var pendingModule: Module?

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
        .sheet(isPresented: $showLogin) { loginSheet }
        .task {
            async let sessionRefresh = session.refresh()
            async let moduleReload: Void = registry.reload()
            async let profileRefresh: Void = profiles.refresh()
            _ = await (sessionRefresh, moduleReload, profileRefresh)
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
}
