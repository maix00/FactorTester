import SwiftUI

struct ServerSettingsView: View {
    @EnvironmentObject var config: ServerConfig
    @Environment(\.dismiss) private var dismiss
    var isInitialSetup = false

    @State private var scheme = "http"
    @State private var host = "127.0.0.1"
    @State private var port = "8000"
    @State private var testResult: String?
    @State private var testing = false
    @State private var showAdvanced = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                header
                connectionCard
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
                        config.save(scheme: scheme, host: host, port: port)
                        if isInitialSetup { dismiss() }
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
                Text("默认连接本机服务；远程与 HTTPS 选项在高级设置中。")
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var connectionCard: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 14) {
                LabeledContent("默认地址") {
                    Text("http://127.0.0.1:8000")
                        .font(.body.monospaced())
                        .foregroundStyle(.secondary)
                }
                Divider()
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
}
