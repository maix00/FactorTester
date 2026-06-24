import SwiftUI

/// 服务器设置 —— 用户自己填网址与端口，保存后可随时回来修改。
struct ServerSettingsView: View {
    @EnvironmentObject var config: ServerConfig
    @Environment(\.dismiss) private var dismiss

    /// 首次配置时为 true：保存后不允许取消（必须先配置才能用）。
    var isInitialSetup: Bool = false

    @State private var scheme: String = "http"
    @State private var host: String = ""
    @State private var port: String = ""
    @State private var testResult: String?
    @State private var testing = false

    var body: some View {
        NavigationStack {
            Form {
                Section("服务器") {
                    Picker("协议", selection: $scheme) {
                        Text("http").tag("http")
                        Text("https").tag("https")
                    }
                    .pickerStyle(.segmented)

                    TextField("主机 / IP（如 192.168.1.10）", text: $host)
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        #endif
                        .autocorrectionDisabled()

                    TextField("端口（如 8000，可留空）", text: $port)
                        #if os(iOS)
                        .keyboardType(.numberPad)
                        #endif
                }

                Section {
                    Button {
                        Task { await test() }
                    } label: {
                        HStack {
                            if testing { ProgressView() }
                            Text("测试连接")
                        }
                    }
                    .disabled(host.trimmingCharacters(in: .whitespaces).isEmpty || testing)

                    if let r = testResult {
                        Text(r).font(.footnote)
                            .foregroundStyle(r.hasPrefix("✓") ? .green : .red)
                    }
                } footer: {
                    Text("自签名证书的 https 服务器已自动放行。地址保存后随时可在此修改。")
                }
            }
            .navigationTitle(isInitialSetup ? "配置服务器" : "服务器设置")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                if !isInitialSetup {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("取消") { dismiss() }
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        config.save(scheme: scheme, host: host, port: port)
                        dismiss()
                    }
                    .disabled(host.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
        .onAppear {
            scheme = config.scheme
            host = config.host
            port = config.port
        }
    }

    private func test() async {
        testing = true; testResult = nil
        defer { testing = false }
        // 临时套用当前输入再调 /api/me（不依赖登录态，仅验证可达）。
        config.save(scheme: scheme, host: host, port: port)
        do {
            _ = try await APIClient.shared.me()
            testResult = "✓ 已连接到服务器"
        } catch {
            testResult = "✗ " + ((error as? APIError)?.errorDescription ?? error.localizedDescription)
        }
    }
}
