import SwiftUI

/// 首页「工具箱」—— home.html 的原生迁移版。
/// 模块网格来自共享注册表（ModuleRegistry → /static/config/modules.json）。
struct HomeView: View {
    @EnvironmentObject var session: SessionStore
    @EnvironmentObject var registry: ModuleRegistry
    @EnvironmentObject var config: ServerConfig

    @State private var path: [Module] = []
    @State private var showLogin = false
    @State private var showSettings = false
    @State private var showClientSettings = false
    @State private var pendingModule: Module?

    private let columns = [GridItem(.adaptive(minimum: Theme.cardMinWidth), spacing: Theme.gridSpacing)]

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                ClientAdapterPanel()
                    .padding(.horizontal, 20)
                    .padding(.top, 20)

                LazyVGrid(columns: columns, spacing: Theme.gridSpacing) {
                    ForEach(registry.visibleModules(forRole: session.role)) { module in
                        ModuleCard(module: module) { tap(module) }
                    }
                }
                .padding(20)

                if registry.isLoading {
                    ProgressView().padding()
                } else if let err = registry.loadError {
                    Text(err).font(.footnote).foregroundStyle(.red).padding()
                }
            }
            .background(Theme.pageBackground)
            .navigationTitle("工具箱")
            .navigationDestination(for: Module.self) { module in
                ModuleDestinationView(module: module)
            }
            .toolbar { toolbarContent }
            .sheet(isPresented: $showLogin) {
                LoginView { didLogin in
                    showLogin = false
                    if didLogin, let m = pendingModule { open(m) }
                    pendingModule = nil
                }
                .environmentObject(session)
            }
            .sheet(isPresented: $showSettings) {
                ServerSettingsView()
                    .environmentObject(config)
            }
            .sheet(isPresented: $showClientSettings) {
                ClientReleaseSettingsView()
            }
        }
        .task {
            await session.refresh()
            await registry.reload()
        }
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .primaryAction) {
            Menu {
                if session.isLoggedIn {
                    Text(session.user?.username ?? "")
                    Button("退出登录", role: .destructive) { Task { await session.logout(); await registry.reload() } }
                } else {
                    Button("登录 / 注册") { showLogin = true }
                }
                Divider()
                Button("服务器设置…") { showSettings = true }
                Button("客户端设置…") { showClientSettings = true }
            } label: {
                Label(session.user?.username ?? "未登录", systemImage: "person.crop.circle")
            }
        }
    }

    private func tap(_ module: Module) {
        if module.requiresAuth && !session.isLoggedIn {
            pendingModule = module
            showLogin = true
        } else {
            open(module)
        }
    }

    private func open(_ module: Module) {
        path.append(module)
    }
}

/// 单张模块卡片 —— 对应 home.html 的 .module-card。
struct ModuleCard: View {
    let module: Module
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 10) {
                icon
                Text(module.title).font(.headline)
                Text(module.desc)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
            .background(Theme.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: Theme.cardCorner, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.cardCorner, style: .continuous)
                    .strokeBorder(.separator, lineWidth: 0.5)
            )
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private var icon: some View {
        if let symbol = module.sfSymbol, !symbol.isEmpty {
            Image(systemName: symbol)
                .font(.system(size: 28))
                .foregroundStyle(Theme.accent)
                .frame(height: 32)
        } else {
            Text(module.icon).font(.system(size: 28)).frame(height: 32)
        }
    }
}
