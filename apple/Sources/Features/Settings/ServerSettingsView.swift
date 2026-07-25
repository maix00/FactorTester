import SwiftUI

struct ServerSettingsView: View {
    @EnvironmentObject var config: ServerConfig
    @EnvironmentObject var managerConfig: ManagerConfig
    @Environment(\.dismiss) private var dismiss
    var isInitialSetup = false

    @State private var scheme = "http"
    @State private var host = "127.0.0.1"
    @State private var port = "8000"
    @State private var managerScheme = "http"
    @State private var managerHost = "127.0.0.1"
    @State private var managerPort = "7998"
    @State private var jobPortText = ""
    @State private var jobPorts = ""
    @State private var testResult: String?
    @State private var testing = false
    @State private var showAdvanced = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                header
                connectionCard
                managerConnectionCard
                jobPortsCard
                HStack {
                    Button("测试连接") { Task { await test() } }
                        .disabled(testing || host.isEmpty)
                    if testing { ProgressView().controlSize(.small) }
                    if let testResult {
                        Text(testResult)
                            .font(.callout)
                            .foregroundStyle(
                                testResult.hasPrefix("✓") ? .green : .red
                            )
                    }
                    Spacer()
                    Button("保存连接") {
                        Task { await saveConnections() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(host.isEmpty)
                }
            }
            .frame(maxWidth: 680, alignment: .leading)
            .padding(28)
        }
        .onAppear {
            scheme = config.scheme
            host = config.host.isEmpty ? "127.0.0.1" : config.host
            port = config.port.isEmpty ? "8000" : config.port
            managerScheme = managerConfig.scheme
            managerHost = managerConfig.host.isEmpty ? "127.0.0.1" : managerConfig.host
            managerPort = managerConfig.port.isEmpty ? "7998" : managerConfig.port
            jobPorts = UserDefaults.standard.string(forKey: "factortester.jobPorts") ?? ""
        }
    }

    private var header: some View {
        HStack(spacing: 16) {
            Image(systemName: "server.rack")
                .font(.system(size: 32))
                .foregroundStyle(.tint)
                .frame(width: 56, height: 56)
                .background(.tint.opacity(0.12), in: RoundedRectangle(cornerRadius: 14))
            VStack(alignment: .leading, spacing: 4) {
                Text(isInitialSetup ? "连接 FactorTester" : "服务器")
                    .font(.largeTitle.weight(.semibold))
                Text("分别配置业务服务和 Manager 的主机与端口。")
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var connectionCard: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 14) {
                DisclosureGroup("高级服务器设置", isExpanded: $showAdvanced) {
                    VStack(spacing: 12) {
                        Picker("协议", selection: $scheme) {
                            Text("HTTP").tag("http")
                            Text("HTTPS").tag("https")
                        }
                        .pickerStyle(.segmented)
                        TextField("主机或 IP", text: $host)
                            .autocorrectionDisabled()
                        TextField("端口", text: $port)
                    }
                    .padding(.top, 10)
                }
                Text("HTTPS 可连接自签名开发服务器；请仅使用可信地址。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(10)
        }
    }

    private var managerConnectionCard: some View {
        GroupBox("Manager") {
            VStack(spacing: 12) {
                Picker("协议", selection: $managerScheme) {
                    Text("HTTP").tag("http")
                    Text("HTTPS").tag("https")
                }
                .pickerStyle(.segmented)
                TextField("主机或 IP", text: $managerHost)
                    .autocorrectionDisabled()
                TextField("Manager 端口", text: $managerPort)
                Text("非本机 Manager 必须使用 HTTPS；登录凭据与业务服务一致。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(10)
        }
    }

    private var jobPortsCard: some View {
        GroupBox("手工任务端口") {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    TextField("端口", text: $jobPortText)
                        .frame(width: 100)
                    Button("加入") {
                        guard let value = Int(jobPortText), 1...65535 ~= value else { return }
                        let existing = jobPorts.split(separator: ",").compactMap { Int($0) }
                        jobPorts = Array(Set(existing + [value])).sorted().map(String.init).joined(separator: ",")
                        jobPortText = ""
                        UserDefaults.standard.set(jobPorts, forKey: "factortester.jobPorts")
                    }
                    Button("清空") {
                        jobPorts = ""
                        UserDefaults.standard.removeObject(forKey: "factortester.jobPorts")
                    }
                }
                Text(jobPorts.isEmpty ? "没有手工端口；测试任务页面会自动从服务器发现端口。" : "已保存：\(jobPorts)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(10)
        }
    }

    private func test() async {
        testing = true
        testResult = nil
        defer { testing = false }
        config.save(scheme: scheme, host: host, port: port)
        do {
            _ = try await APIClient.shared.me()
            testResult = "✓ 已连接"
        } catch {
            testResult = "✗ " + (
                (error as? APIError)?.errorDescription
                    ?? error.localizedDescription
            )
        }
    }

    private func saveConnections() async {
        config.save(scheme: scheme, host: host, port: port)
        managerConfig.save(
            scheme: managerScheme,
            host: managerHost,
            port: managerPort
        )
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
