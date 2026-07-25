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
    @State private var saving = false

    var body: some View {
        SettingsPageShell(
            title: isInitialSetup ? "连接 FactorTester" : "服务器",
            subtitle: "配置 Manager；具体 FactorTester 服务端口由 Manager 发现。",
            systemImage: "server.rack"
        ) {
            SettingsSectionCard("Manager") {
                SettingsRow(title: "协议", description: "Manager 管理接口的传输协议。") {
                    Picker("协议", selection: $managerScheme) {
                        Text("HTTP").tag("http")
                        Text("HTTPS").tag("https")
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                }
                Divider()
                SettingsRow(title: "网址", description: "Manager 主机名或 IP。") {
                    TextField("主机或 IP", text: $managerHost)
                        .autocorrectionDisabled()
                        .textFieldStyle(.roundedBorder)
                }
                Divider()
                SettingsRow(title: "端口", description: "Manager 管理端口，默认 7998。") {
                    TextField("Manager 端口", text: $managerPort)
                        .textFieldStyle(.roundedBorder)
                }
            }

            SettingsSectionCard("FactorTester 服务端口") {
                SettingsRow(title: "当前端口", description: "由 Manager 返回的可用服务端口；不再手工添加端口。") {
                    HStack(spacing: 8) {
                        Text(currentServicePort)
                            .monospacedDigit()
                            .foregroundStyle(.secondary)
                        SettingsRefreshButton(isWorking: discoveringPorts) {
                            Task { await discoverPorts() }
                        }
                    }
                }
                if let testResult {
                    Divider()
                    Text(testResult)
                        .font(.callout)
                        .foregroundStyle(testResult.hasPrefix("✓") ? .green : .red)
                        .padding(.vertical, 8)
                }
            }

            HStack {
                Button("测试连接") { Task { await test() } }
                    .buttonStyle(.bordered)
                    .disabled(testing || managerHost.trimmingCharacters(in: .whitespaces).isEmpty)
                if testing { ProgressView().controlSize(.small) }
                Spacer()
                Button("保存连接") { Task { await saveConnections() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(saving || managerHost.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .task {
            loadValues()
            await discoverPorts()
        }
    }

    private var currentServicePort: String {
        if let value = Int(port.trimmingCharacters(in: .whitespaces)), value > 0 {
            return String(value)
        }
        if let first = availablePorts.first { return "自动 · \(first)" }
        return "自动 · 未发现"
    }

    private func loadValues() {
        port = config.port
        managerScheme = managerConfig.scheme
        managerHost = managerConfig.host
        managerPort = managerConfig.port
    }

    @MainActor
    private func discoverPorts() async {
        discoveringPorts = true
        defer { discoveringPorts = false }
        availablePorts = (try? await ManagerCLIClient.shared.availableServicePorts()) ?? []
    }

    private func test() async {
        await MainActor.run { testing = true; testResult = nil }
        defer { Task { @MainActor in testing = false } }
        let effectivePort = port.trimmingCharacters(in: .whitespaces).isEmpty
            ? availablePorts.first.map(String.init) ?? ""
            : port
        config.save(scheme: managerScheme, host: managerHost, port: effectivePort)
        do {
            _ = try await APIClient.shared.me()
            await MainActor.run { testResult = "✓ 已连接" }
        } catch {
            await MainActor.run {
                testResult = "✗ " + ((error as? APIError)?.errorDescription ?? error.localizedDescription)
            }
        }
    }

    @MainActor
    private func saveConnections() async {
        saving = true
        defer { saving = false }
        let effectivePort = port.trimmingCharacters(in: .whitespaces).isEmpty
            ? availablePorts.first.map(String.init) ?? ""
            : port
        config.save(scheme: managerScheme, host: managerHost, port: effectivePort)
        managerConfig.save(scheme: managerScheme, host: managerHost, port: managerPort)
        do {
            try await ManagerCLIClient.shared.configure(
                scheme: managerScheme,
                host: managerHost,
                port: managerPort
            )
            testResult = "✓ 已保存"
            if isInitialSetup { dismiss() }
        } catch {
            testResult = "✗ " + error.localizedDescription
        }
    }
}
