import SwiftUI

struct ClientReleaseSettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var controller = ClientReleaseController()
    var embedded = false

    var body: some View {
        Group {
            if embedded {
                updatePanel
            } else {
                VStack(spacing: 0) {
                    header
                    Divider()
                    TabView {
                        updatePanel
                            .tabItem {
                                Label("客户端更新", systemImage: "arrow.down.app")
                            }
                        LocalProfilesView()
                            .tabItem {
                                Label("Profiles", systemImage: "person.2")
                            }
                    }
                }
            }
        }
        .frame(width: 720, height: 620)
        .background(.regularMaterial)
        .task { await controller.refresh() }
    }

    private var header: some View {
        HStack(spacing: 14) {
            Image(systemName: "arrow.triangle.2.circlepath.circle.fill")
                .font(.system(size: 34))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 3) {
                Text("FTClient")
                    .font(.title2.weight(.semibold))
                Text("更新客户端，并管理所有人类与 Agent Profiles")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Button("关闭") { dismiss() }
                .keyboardShortcut(.cancelAction)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 18)
    }

    private var updatePanel: some View {
        ScrollView {
            VStack(spacing: 18) {
                ClientReleaseStatusCard(controller: controller)
                GroupBox("更新策略") {
                    VStack(alignment: .leading, spacing: 12) {
                        Picker("渠道", selection: $controller.channel) {
                            Text("Main · GitHub").tag("stable")
                            Text("Beta · 服务器").tag("beta")
                        }
                        .pickerStyle(.segmented)
                        Toggle(
                            "启动时自动检查（最多每 6 小时一次）",
                            isOn: $controller.automaticallyChecks
                        )
                        if let checked = controller.lastChecked {
                            LabeledContent(
                                "最后检查",
                                value: checked.formatted(
                                    date: .abbreviated, time: .shortened
                                )
                            )
                        }
                    }
                    .padding(8)
                }
                GroupBox("安全状态") {
                    LabeledContent("App 签名", value: controller.signatureText)
                        .padding(8)
                }
                GroupBox("更新来源") {
                    LabeledContent(
                        controller.channel == "beta" ? "Beta" : "Main",
                        value: controller.channel == "beta"
                            ? "当前 FactorTester 服务器"
                            : "GitHub · maix00/FactorTester-Client"
                    )
                    .padding(8)
                    Text(controller.channel == "beta"
                        ? "Beta 仅从当前服务器获取，并使用独立的 Beta 信任密钥验证；不会回退到 GitHub。"
                        : "Main 仅从 GitHub 的签名发布清单获取；不会回退到服务器 Beta。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 8)
                        .padding(.bottom, 8)
                }
                if let message = controller.lastError {
                    Label(message, systemImage: "info.circle.fill")
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(12)
                        .background(.blue.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
                }
                HStack {
                    Button("检查更新") {
                        Task { await controller.refresh() }
                    }
                    Spacer()
                    Button("打开上一版 DMG") {
                        Task { await controller.rollback() }
                    }
                    .disabled(!controller.canRollback)
                    Button("验证、下载并打开 DMG") {
                        Task { await controller.update() }
                    }
                    .buttonStyle(.borderedProminent)
                }
                .disabled(controller.isWorking)
            }
            .padding(24)
        }
    }
}
