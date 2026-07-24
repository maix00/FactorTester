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
        .frame(width: 640, height: 480)
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
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 14) {
                Image(systemName: statusIcon)
                    .font(.system(size: 30))
                    .foregroundStyle(statusTint)
                VStack(alignment: .leading, spacing: 3) {
                    Text(statusTitle)
                        .font(.title3.weight(.semibold))
                    Text(statusSubtitle)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if controller.isWorking {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            Picker("更新渠道", selection: $controller.channel) {
                Text("Main").tag("stable")
                Text("Beta").tag("beta")
            }
            .pickerStyle(.segmented)

            Toggle(
                "自动下载更新",
                isOn: $controller.automaticallyUpdates
            )

            if let message = controller.lastError {
                Label(message, systemImage: "info.circle")
                    .font(.callout)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(
                        Color.blue.opacity(0.08),
                        in: RoundedRectangle(cornerRadius: 9)
                    )
            }

            Button(action: primaryAction) {
                Label(primaryTitle, systemImage: primaryIcon)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(controller.isWorking)

            DisclosureGroup("更新详情") {
                VStack(alignment: .leading, spacing: 10) {
                    LabeledContent("当前版本", value: installedVersion)
                    if !controller.latestVersion.isEmpty {
                        LabeledContent(
                            "可用版本",
                            value: controller.latestVersion
                        )
                    }
                    LabeledContent("来源", value: sourceLabel)
                    LabeledContent("签名", value: controller.signatureText)
                    if let checked = controller.lastChecked {
                        LabeledContent(
                            "最后检查",
                            value: checked.formatted(
                                date: .abbreviated,
                                time: .shortened
                            )
                        )
                    }
                    if controller.canRollback {
                        Button("准备上一版") {
                            Task { await controller.rollback() }
                        }
                    }
                }
                .padding(.top, 8)
            }
            .font(.callout)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }

    private var installedVersion: String {
        controller.installedVersion.isEmpty
            ? L10n.text("未知") : controller.installedVersion
    }

    private var statusTitle: String {
        if controller.pendingUpdate != nil {
            return L10n.text("更新已准备好")
        }
        if controller.hasAvailableUpdate {
            return L10n.text("发现新版本")
        }
        if controller.isWorking {
            return L10n.text("正在检查更新")
        }
        return L10n.text("FTClient 已是最新状态")
    }

    private var statusSubtitle: String {
        if let pending = controller.pendingUpdate {
            return L10n.text("\(pending.version) 将在重启后安装")
        }
        if controller.hasAvailableUpdate {
            return L10n.text("\(controller.latestVersion) 可以下载")
        }
        return L10n.text("当前版本 \(installedVersion)")
    }

    private var statusIcon: String {
        if controller.pendingUpdate != nil { return "arrow.clockwise.circle.fill" }
        if controller.hasAvailableUpdate { return "arrow.down.circle.fill" }
        return "checkmark.circle.fill"
    }

    private var statusTint: Color {
        controller.pendingUpdate != nil || controller.hasAvailableUpdate
            ? .accentColor : .green
    }

    private var primaryTitle: String {
        if controller.pendingUpdate != nil { return L10n.text("重启并更新") }
        if controller.hasAvailableUpdate { return L10n.text("下载更新") }
        return L10n.text("检查更新")
    }

    private var primaryIcon: String {
        if controller.pendingUpdate != nil { return "arrow.clockwise" }
        if controller.hasAvailableUpdate { return "arrow.down" }
        return "arrow.triangle.2.circlepath"
    }

    private var sourceLabel: String {
        controller.channel == "beta"
            ? L10n.text("Beta · FactorTester 服务器")
            : L10n.text("Main · GitHub")
    }

    private func primaryAction() {
        Task {
            if controller.pendingUpdate != nil {
                await controller.restartToApply()
            } else if controller.hasAvailableUpdate {
                await controller.update()
            } else {
                await controller.refresh()
            }
        }
    }
}
