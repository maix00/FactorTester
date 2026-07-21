import SwiftUI

struct ClientReleaseSettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var controller: ClientReleaseController
    var embedded = false

    init(controller: ClientReleaseController, embedded: Bool = false) {
        self.controller = controller
        self.embedded = embedded
    }

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
                            "自动下载当前渠道更新（Beta / 稳定版）",
                            isOn: $controller.automaticallyUpdates
                        )
                        Text("下载完成后不会自动替换正在运行的 App；左下角‘设置’旁会提示‘重启更新’。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
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
                    Button("准备上一版并重启") {
                        Task { await controller.rollback() }
                    }
                    .disabled(!controller.canRollback)
                    Button("下载并准备更新") {
                        Task { await controller.update() }
                    }
                    .buttonStyle(.borderedProminent)
                }
                .disabled(controller.isWorking)
                if let pending = controller.pendingUpdate {
                    GroupBox("已准备好的更新") {
                        VStack(alignment: .leading, spacing: 10) {
                            Label(
                                "(pending.version) · (pending.channel)",
                                systemImage: "arrow.down.app.fill"
                            )
                            Text("更新包已通过校验，重启后自动切换；当前研究任务不会被后台强制中断。")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Button("重启应用更新") {
                                Task { await controller.restartToApply() }
                            }
                            .buttonStyle(.borderedProminent)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(8)
                    }
                }
            }
            .padding(24)
        }
    }
}
