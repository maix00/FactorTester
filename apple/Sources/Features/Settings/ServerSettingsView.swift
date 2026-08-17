import SwiftUI

struct ServerSettingsView: View {
    @EnvironmentObject var config: ServerConfig
    @EnvironmentObject var managerConfig: ManagerConfig
    @EnvironmentObject var session: SessionStore
    @Environment(\.dismiss) private var dismiss
    var isInitialSetup = false
    var onConfigured: (() -> Void)? = nil

    @State private var port = ""
    @State private var managerScheme = "http"
    @State private var managerHost = "127.0.0.1"
    @State private var managerPort = "7998"
    @State private var managerServerID = ""
    @State private var originManagerEndpoint: URL?
    @State private var currentDeviceAudit: ManagerDeviceAudit?
    @State private var availablePorts: [Int] = []
    @State private var discoveringPorts = false
    @State private var testResult: String?
    @State private var testing = false
    @State private var editingManagerScheme = false

    var body: some View {
        SettingsPageShell(
            title: SettingsDisplayText(
                isInitialSetup ? "连接 FactorTester" : "服务器"
            ),
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
                SettingsRow(
                    title: "当前服务器 ID",
                    description: "由内网 Manager 的服务器登记信息提供；切换公网时不在客户端硬编码"
                ) {
                    Text(managerServerID.isEmpty ? L10n.text("尚未由服务器提供") : managerServerID)
                        .foregroundStyle(.secondary)
                }
                if let currentDeviceAudit {
                    Divider()
                    SettingsRow(
                        title: "本机登记信息",
                        description: "服务器记录的客户端类型、登记 IP 与最近访问 IP"
                    ) {
                        VStack(alignment: .trailing, spacing: 3) {
                            Text(currentDeviceAudit.clientName.isEmpty
                                ? L10n.text("Swift 客户端")
                                : currentDeviceAudit.clientName)
                            Text(
                                "\(L10n.text("登记 IP"))：\(currentDeviceAudit.enrollmentIP.isEmpty ? L10n.text("未记录") : currentDeviceAudit.enrollmentIP)"
                            )
                            Text(
                                "\(L10n.text("最近访问 IP"))：\(currentDeviceAudit.lastSeenIP.isEmpty ? L10n.text("未记录") : currentDeviceAudit.lastSeenIP)"
                            )
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                    }
                }
                Divider()
                HStack {
                    Button(
                        managerTargetIsPrivateNetwork
                            ? "测试连接"
                            : "切换并认证公网 Manager"
                    ) { Task { await test() } }
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
                Divider()
                Button("发现并切换到最近公网 Manager") {
                    Task { await switchToNearestPublicManager() }
                }
                .buttonStyle(.borderedProminent)
                .disabled(testing || managerHost.trimmingCharacters(in: .whitespaces).isEmpty)
            }

            SettingsSectionCard("FactorTester 服务端口") {
                SettingsRow(
                    title: "服务端口",
                    description: "可填写固定端口；留空时由 Manager 自动选择可用端口"
                ) {
                    HStack(spacing: 8) {
                        SettingsEditableText(
                            value: $port,
                            placeholder: .verbatim(
                                L10n.format(
                                    "空值（自动选择的 %@）",
                                    automaticPortText
                                )
                            ),
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
            await refreshDeviceAudit()
        }
        .onChange(of: managerScheme) { value in managerConfig.scheme = value }
        .onChange(of: managerHost) { value in
            managerConfig.host = value
            config.host = value
        }
        .onChange(of: managerPort) { value in managerConfig.port = value }
        .onChange(of: managerServerID) { value in managerConfig.serverID = value }
        .onChange(of: port) { value in config.port = value }
        .onDisappear { Task { await synchronizeManagerConfiguration() } }
    }

    private func loadValues() {
        port = config.port
        managerScheme = managerConfig.scheme
        managerHost = managerConfig.host
        managerPort = managerConfig.port
        managerServerID = managerConfig.serverID
        originManagerEndpoint = managerConfig.baseURL
    }

    private var managerTargetIsPrivateNetwork: Bool {
        ManagerEndpointPolicy.isPrivateNetwork(managerHost)
    }

    private var automaticPortText: String {
        availablePorts.first.map {
            L10n.format("%lld 端口", $0)
        } ?? L10n.text("端口尚未返回")
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
        if isInitialSetup {
            await connectInitialManager(effectivePort: effectivePort)
            return
        }
        if !managerTargetIsPrivateNetwork {
            guard let target = managerConfig.baseURL else {
                testResult = "✗ " + L10n.text("设备认证地址无效。")
                return
            }
            do {
                let result = try await ManagerDeviceAuthenticationService.shared.authenticate(
                    endpoint: target
                )
                config.save(scheme: managerScheme, host: managerHost, port: effectivePort)
                try await ManagerCLIClient.shared.configure(
                    scheme: managerScheme,
                    host: managerHost,
                    port: managerPort
                )
                originManagerEndpoint = target
                await refreshDeviceAudit()
                testResult = "✓ " + L10n.format(
                    "已通过原生设备密钥认证：%@",
                    result.username
                )
                if isInitialSetup, onConfigured == nil { dismiss() }
            } catch {
                testResult = "✗ " + ((error as? APIError)?.errorDescription ?? error.localizedDescription)
            }
            return
        }
        config.save(scheme: managerScheme, host: managerHost, port: effectivePort)
        do {
            try await ManagerCLIClient.shared.configure(
                scheme: managerScheme,
                host: managerHost,
                port: managerPort
            )
            _ = try await APIClient.shared.me()
            testResult = "✓ " + L10n.text("已连接")
            if isInitialSetup, onConfigured == nil { dismiss() }
        } catch {
            testResult = "✗ " + ((error as? APIError)?.errorDescription ?? error.localizedDescription)
        }
    }

    /// Initial setup only proves that the selected Manager is reachable. A
    /// public Manager may require a device key for ordinary authenticated
    /// operations, but that key must not be a prerequisite for opening the
    /// client and showing its normal login page.
    @MainActor
    private func connectInitialManager(effectivePort: String) async {
        managerConfig.save(
            scheme: managerScheme,
            host: managerHost,
            port: managerPort,
            serverID: "",
            source: .manual
        )
        guard managerConfig.isValid, let endpoint = managerConfig.baseURL else {
            testResult = "✗ " + L10n.text("Manager 地址无效；公网必须使用 HTTPS。")
            return
        }
        do {
            let info = try await ManagerNetworkInfoService.shared.fetch(
                endpoint: endpoint
            )
            managerConfig.save(
                scheme: managerScheme,
                host: managerHost,
                port: managerPort,
                serverID: info.serverID,
                source: .manual
            )
            config.save(scheme: managerScheme, host: managerHost, port: effectivePort)
            try? await ManagerCLIClient.shared.configure(
                scheme: managerScheme,
                host: managerHost,
                port: managerPort
            )
            originManagerEndpoint = endpoint
            managerServerID = info.serverID
            await discoverPorts()
            testResult = "✓ " + L10n.text("已连接；请在主页按需登录")
            onConfigured?()
            if isInitialSetup, onConfigured == nil { dismiss() }
        } catch {
            testResult = "✗ " + ((error as? APIError)?.errorDescription ?? error.localizedDescription)
        }
    }

    @MainActor
    private func switchToNearestPublicManager() async {
        testing = true
        testResult = nil
        defer { testing = false }
        do {
            guard await ManagerEndpointDiscoveryService.shared.selectBestManager(
                organizationID: session.user?.organizationId,
                force: true
            ) != nil else {
                throw APIError.server(L10n.text("没有可访问的公网 Manager。"))
            }
            managerScheme = managerConfig.scheme
            managerHost = managerConfig.host
            managerPort = managerConfig.port
            managerServerID = managerConfig.serverID
            config.host = managerHost
            await discoverPorts()
            let effectivePort = port.trimmingCharacters(in: .whitespaces).isEmpty
                ? availablePorts.first.map(String.init) ?? config.port
                : port
            config.save(
                scheme: managerScheme,
                host: managerHost,
                port: effectivePort
            )
            try await ManagerCLIClient.shared.configure(
                scheme: managerScheme,
                host: managerHost,
                port: managerPort
            )
            originManagerEndpoint = managerConfig.baseURL
            await refreshDeviceAudit()
            testResult = "✓ " + L10n.format(
                "已自动选择服务器 %@",
                managerServerID
            )
            onConfigured?()
            if isInitialSetup, onConfigured == nil { dismiss() }
        } catch {
            testResult = "✗ " + ((error as? APIError)?.errorDescription ?? error.localizedDescription)
        }
    }

    @MainActor
    private func synchronizeManagerConfiguration() async {
        managerConfig.save(
            scheme: managerScheme,
            host: managerHost,
            port: managerPort,
            serverID: managerServerID
        )
        config.host = managerHost
        config.port = port
        try? await ManagerCLIClient.shared.configure(
            scheme: managerScheme,
            host: managerHost,
            port: managerPort
        )
    }

    @MainActor
    private func refreshDeviceAudit() async {
        currentDeviceAudit = try? await ManagerDeviceRegistryService.shared
            .currentDevice(endpoint: managerConfig.baseURL)
    }
}
