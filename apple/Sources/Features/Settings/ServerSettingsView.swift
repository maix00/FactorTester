import SwiftUI

struct ServerSettingsView: View {
    @EnvironmentObject var config: ServerConfig
    @EnvironmentObject var managerConfig: ManagerConfig
    @Environment(\.dismiss) private var dismiss
    var isInitialSetup = false

    @State private var port = ""
    @State private var managerScheme = "http"
    @State private var managerHost = "127.0.0.1"
    @State private var managerPort = "7998"
    @State private var availablePorts: [Int] = []
    @State private var discoveringPorts = false
    @State private var testResult: String?
    @State private var testing = false
    @State private var editingManagerScheme = false

    var body: some View {
        SettingsPageShell(
            title: isInitialSetup ? "连接 FactorTester" : "服务器",
            subtitle: "配置 Manager；具体 FactorTester 服务端口由 Manager 发现",
            systemImage: "server.rack"
        ) {
            SettingsSectionCard("Manager") {
                SettingsRow(title: "协议", description: "Manager 管理接口的传输协议") {
                    if editingManagerScheme {
                        Picker("协议", selection: $managerScheme) {
                            Text("HTTP").tag("http")
                            Text("HTTPS").tag("https")
                        }
                        .pickerStyle(.segmented)
                        .labelsHidden()
                        .onChange(of: managerScheme) { _ in
                            editingManagerScheme = false
                            Task { await synchronizeManagerConfiguration() }
                        }
                    } else {
                        Button {
                            editingManagerScheme = true
                        } label: {
                            Text(managerScheme.uppercased())
                                .foregroundStyle(.primary)
                        }
                        .buttonStyle(.plain)
                        .help("点击修改")
                    }
                }
                Divider()
                SettingsRow(title: "网址", description: "Manager 主机名或 IP") {
                    SettingsEditableText(
                        value: $managerHost,
                        placeholder: "主机或 IP",
                        onCommit: { Task { await synchronizeManagerConfiguration() } }
                    )
                }
                Divider()
                SettingsRow(title: "端口", description: "Manager 管理端口，默认 7998") {
                    SettingsEditableText(
                        value: $managerPort,
                        placeholder: "Manager 端口",
                        onCommit: { Task { await synchronizeManagerConfiguration() } }
                    )
                }
                Divider()
                HStack {
                    Button("测试连接") { Task { await test() } }
                        .buttonStyle(.bordered)
                        .disabled(testing || managerHost.trimmingCharacters(in: .whitespaces).isEmpty)
                    if testing { ProgressView().controlSize(.small) }
                    if let testResult {
                        Text(testResult)
                            .font(.callout)
                            .foregroundStyle(testResult.hasPrefix("✓") ? .green : .red)
                    }
                    Spacer()
                }
                .padding(.vertical, 8)
            }

            SettingsSectionCard("FactorTester 服务端口") {
                SettingsRow(
                    title: "服务端口",
                    description: "可填写固定端口；留空时由 Manager 自动选择可用端口"
                ) {
                    HStack(spacing: 8) {
                        SettingsEditableText(
                            value: $port,
                            placeholder: "空值（自动选择的 \(automaticPortText)）",
                            onCommit: { Task { await synchronizeManagerConfiguration() } }
                        )
                        SettingsRefreshButton(isWorking: discoveringPorts) {
                            Task { await discoverPorts() }
                        }
                    }
                }
            }
        }
        .task {
            loadValues()
            await discoverPorts()
        }
        .onChange(of: managerScheme) { value in managerConfig.scheme = value }
        .onChange(of: managerHost) { value in
            managerConfig.host = value
            config.host = value
        }
        .onChange(of: managerPort) { value in managerConfig.port = value }
        .onChange(of: port) { value in config.port = value }
        .onDisappear { Task { await synchronizeManagerConfiguration() } }
    }

    private func loadValues() {
        port = config.port
        managerScheme = managerConfig.scheme
        managerHost = managerConfig.host
        managerPort = managerConfig.port
    }

    private var automaticPortText: String {
        availablePorts.first.map { "\($0) 端口" } ?? "端口尚未返回"
    }

    @MainActor
    private func discoverPorts() async {
        discoveringPorts = true
        defer { discoveringPorts = false }
        availablePorts = (try? await ManagerCLIClient.shared.availableServicePorts()) ?? []
    }

    @MainActor
    private func test() async {
        testing = true
        testResult = nil
        defer { testing = false }
        let effectivePort = port.trimmingCharacters(in: .whitespaces).isEmpty
            ? availablePorts.first.map(String.init) ?? ""
            : port
        config.save(scheme: managerScheme, host: managerHost, port: effectivePort)
        do {
            try await ManagerCLIClient.shared.configure(
                scheme: managerScheme,
                host: managerHost,
                port: managerPort
            )
            _ = try await APIClient.shared.me()
            testResult = "✓ 已连接"
            if isInitialSetup { dismiss() }
        } catch {
            testResult = "✗ " + ((error as? APIError)?.errorDescription ?? error.localizedDescription)
        }
    }

    @MainActor
    private func synchronizeManagerConfiguration() async {
        managerConfig.save(scheme: managerScheme, host: managerHost, port: managerPort)
        config.host = managerHost
        config.port = port
        try? await ManagerCLIClient.shared.configure(
            scheme: managerScheme,
            host: managerHost,
            port: managerPort
        )
    }
}
