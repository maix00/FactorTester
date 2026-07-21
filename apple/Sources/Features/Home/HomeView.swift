import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var session: SessionStore
    @EnvironmentObject private var registry: ModuleRegistry
    @EnvironmentObject private var config: ServerConfig

    @StateObject private var profiles = LocalProfileController()
    @State private var tabs: [ClientTab] = [.home]
    @State private var selection = ClientTab.home.id
    @State private var showLogin = false
    @State private var pendingModule: Module?

    var body: some View {
        NavigationSplitView {
            ClientSidebar(
                selection: $selection,
                openTabs: tabs,
                open: open,
                close: close
            )
        } detail: {
            ZStack {
                dashboard
                    .opacity(selection == ClientTab.home.id ? 1 : 0)
                    .allowsHitTesting(selection == ClientTab.home.id)
                ForEach(tabs.filter { !$0.isHome }) { tab in
                    ClientTabView(
                        tab: tab,
                        profiles: profiles,
                        open: open,
                        isActive: selection == tab.id
                    )
                        .opacity(selection == tab.id ? 1 : 0)
                        .allowsHitTesting(selection == tab.id)
                }
            }
            .navigationTitle(selectedTab?.title ?? ClientTab.home.title)
        }
        .sheet(isPresented: $showLogin) { loginSheet }
        .task {
            await session.refresh()
            await registry.reload()
            await profiles.refresh()
        }
    }

    private var dashboard: some View {
        HomeDashboardView(
            modules: registry.visibleModules(forRole: session.role),
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

    private func close(_ tab: ClientTab) {
        guard tab.isClosable else { return }
        tabs.removeAll { $0.id == tab.id }
        if selection == tab.id { selection = ClientTab.home.id }
    }

    private var selectedTab: ClientTab? {
        tabs.first { $0.id == selection }
    }
}
