import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var session: SessionStore
    @EnvironmentObject private var registry: ModuleRegistry
    @EnvironmentObject private var config: ServerConfig

    @State private var tabs: [ClientTab] = [.home]
    @State private var selection = ClientTab.home.id
    @State private var showLogin = false
    @State private var showSettings = false
    @State private var showClientSettings = false
    @State private var showAccountCenter = false
    @State private var pendingModule: Module?

    var body: some View {
        TabView(selection: $selection) {
            dashboard
                .tabItem { Label("主页", systemImage: "square.grid.2x2") }
                .tag(ClientTab.home.id)

            ForEach(tabs.filter { !$0.isHome }) { tab in
                ClientTabView(
                    tab: tab,
                    goHome: { selection = ClientTab.home.id },
                    close: { close(tab) }
                )
                .tabItem {
                    Label(tab.title, systemImage: tab.systemImage)
                }
                .tag(tab.id)
            }
        }
        .toolbar { toolbarContent }
        .sheet(isPresented: $showLogin) { loginSheet }
        .sheet(isPresented: $showSettings) {
            ServerSettingsView().environmentObject(config)
        }
        .sheet(isPresented: $showClientSettings) {
            ClientReleaseSettingsView()
        }
        .sheet(isPresented: $showAccountCenter) {
            AccountCenterView { destination in
                showAccountCenter = false
                open(destination)
            }
                .environmentObject(session)
        }
        .task {
            await session.refresh()
            await registry.reload()
        }
    }

    private var dashboard: some View {
        HomeDashboardView(
            modules: registry.visibleModules(forRole: session.role),
            isLoading: registry.isLoading,
            loadError: registry.loadError,
            openModule: tap,
            openAdapter: { open(.adapter($0)) }
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

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .primaryAction) {
            Menu {
                if session.isLoggedIn {
                    Button("个人中心…") { showAccountCenter = true }
                    Button("退出登录", role: .destructive) {
                        Task {
                            await session.logout()
                            await registry.reload()
                        }
                    }
                } else {
                    Button("登录 / 注册") { showLogin = true }
                }
                Divider()
                Button("服务器设置…") { showSettings = true }
                Button("客户端与 Profiles…") {
                    showClientSettings = true
                }
            } label: {
                Label(
                    session.user?.username ?? "未登录",
                    systemImage: "person.crop.circle"
                )
            }
        }
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
        tabs.removeAll { $0.id == tab.id }
        selection = ClientTab.home.id
    }
}
